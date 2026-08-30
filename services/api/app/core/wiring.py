"""Bind the module-level service factories that `create_app` leaves unset.

Two routers -- progress and voice -- resolve their service through a module
global that a wiring step is supposed to set. Nothing set them, in `app/` or in
the tests, so every `/progress/*` and `/voice/*` route answered 503
`... is not configured` in every running instance. The README's own example log
line, `503 GET /voice/health`, is that defect being demonstrated rather than a
deployment without a voice tier.

Kept out of the routers so the seam survives: a test still overrides a factory
directly, and this module is the only thing that knows what production wires in.
"""

from __future__ import annotations

import structlog
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gateway import LlmGateway, Provider
from app.core.config import Settings
from app.core.redis import get_redis
from app.modules.chat.repository import ChatRepository
from app.modules.chat.router import set_chat_service_factory
from app.modules.chat.service import ChatService
from app.modules.children.consent_gate import ConsentGate
from app.modules.progress.history import ProgressHistory
from app.modules.progress.repository import ProgressRepository
from app.modules.progress.router import set_progress_service_factory
from app.modules.progress.service import ProgressService
from app.modules.recommendation.repository import RecommendationRepository
from app.modules.recommendation.router import set_recommendation_service_factory
from app.modules.recommendation.service import RecommendationService
from app.modules.tutor.repository import TutorRepository
from app.modules.tutor.router import set_tutor_service_factory
from app.modules.tutor.service import TutorService
from app.modules.voice.providers import AsrChain, groq_whisper_provider, qwen_provider
from app.modules.voice.router import set_voice_service_factory
from app.modules.voice.service import VoiceService
from app.modules.voice.storage import S3AudioSink
from app.modules.voice.transport import HttpxAsrTransport

logger = structlog.get_logger(__name__)


def _redis_or_none() -> Redis | None:
    """The consent gate's cache. Absent outside a lifespan, which is correct.

    Without Redis the gate reads Postgres directly -- slower, and fail-closed,
    which is the right direction for a consent check to fail in.
    """
    try:
        return get_redis()
    except RuntimeError:
        return None


def build_asr_chain(settings: Settings) -> AsrChain:
    """The recognisers, in failover order (docs/12 §3).

    An empty chain is a supported, documented state, not a misconfiguration:
    `AsrChain` answers `unavailable` rather than raising, the child app shows
    "the microphone is not working right now", and the caregiver-confirm button
    -- which is always on screen anyway -- carries the attempt. That is the mode
    the preflight describes as "ASR failover stops at caregiver confirmation".
    """
    providers = []
    if settings.asr_qwen_base_url:
        providers.append(qwen_provider(HttpxAsrTransport(base_url=settings.asr_qwen_base_url)))
    if settings.groq_api_key:
        providers.append(
            groq_whisper_provider(
                HttpxAsrTransport(base_url=settings.groq_base_url, api_key=settings.groq_api_key)
            )
        )
    if not providers:
        logger.info("asr_no_providers_configured")
    return AsrChain(providers)


def build_gateway(settings: Settings) -> LlmGateway:
    """The one LLM gateway for the process.

    Built unconditionally, including with no key and `AI_LIVE=0`. That is the
    normal configuration, not a degraded one: the gateway replays recorded
    fixtures and makes no network call, and every decision point downstream has
    a deterministic fallback for the case where no fixture exists either.
    Constructing it only when a key is present would mean the fixture path --
    which is how the whole product is verified -- was reachable only in tests.

    One instance rather than one per request. `AsyncAnthropic` and the httpx
    client each own a connection pool, and a pool per request is a pool per
    request.
    """
    provider = Provider(settings.ai_provider)
    gateway = LlmGateway(
        live=settings.ai_live,
        api_key=settings.ai_api_key,
        provider=provider,
        groq_base_url=settings.groq_base_url,
    )
    logger.info(
        "ai_gateway_built",
        provider=provider.value,
        live=settings.ai_live,
        keyed=bool(settings.ai_api_key),
    )
    return gateway


def install_service_factories(settings: Settings) -> None:
    """Called once from `create_app`."""

    def progress_factory(session: AsyncSession) -> ProgressService:
        return ProgressService(
            store=ProgressRepository(session),
            history=ProgressHistory(session),
        )

    # The chain is built once: a provider holds only a base URL and a key, and
    # rebuilding it per request would re-read settings on every attempt.
    asr = build_asr_chain(settings)

    def voice_factory(session: AsyncSession) -> VoiceService:
        return VoiceService(
            asr=asr,
            consent=ConsentGate(session, _redis_or_none()),
            sink=S3AudioSink(settings),
        )

    # Also built once. What the gateway holds is a connection pool and the
    # fixture store's directory handle; per-request would mean per-request.
    gateway = build_gateway(settings)

    def recommendation_factory(session: AsyncSession) -> RecommendationService:
        return RecommendationService(
            repository=RecommendationRepository(session),
            consent=ConsentGate(session, _redis_or_none()),
            gateway=gateway,
        )

    def chat_factory(session: AsyncSession) -> ChatService:
        # Chat borrows the recommendation service's retriever rather than owning
        # a second one. One index, one embedder, and one place where retrieval
        # is scoped to a single child.
        return ChatService(
            repository=ChatRepository(session),
            recommendations=recommendation_factory(session),
            consent=ConsentGate(session, _redis_or_none()),
            gateway=gateway,
        )

    def tutor_factory(session: AsyncSession) -> TutorService:
        # Built here rather than resolved through another module's factory: the
        # tutor loop OWNS the mastery fold and the progress rollup -- they are
        # part of what answering an activity means, not optional collaborators
        # a deployment might omit. Wiring them through settable hooks would
        # make "no skill ever reached mastered" a configuration state rather
        # than a bug, which is the defect the mastery loop was written to fix.
        from app.modules.children.repository import ChildrenRepository
        from app.modules.identity.deps import get_identity_service  # noqa: F401
        from app.modules.identity.ratelimit import RateLimiter
        from app.modules.identity.repository import IdentityRepository
        from app.modules.identity.service import IdentityService
        from app.modules.identity.sms import build_sms_provider
        from app.modules.learning.repository import LearningRepository
        from app.modules.learning.service import MasteryService
        from app.modules.tutor_ai.audit import TutorAuditRepository

        redis = _redis_or_none()
        identity = IdentityService(
            repo=IdentityRepository(session),
            limiter=RateLimiter(redis) if redis is not None else None,  # type: ignore[arg-type]
            sms=build_sms_provider(settings),
            settings=settings,
        )
        return TutorService(
            repo=TutorRepository(session),
            children=ChildrenRepository(session),
            identity=identity,
            mastery=MasteryService(repo=LearningRepository(session)),
            progress=ProgressService(
                store=ProgressRepository(session), history=ProgressHistory(session)
            ),
            audit=TutorAuditRepository(session),
            gateway=gateway,
        )

    set_progress_service_factory(progress_factory)
    set_voice_service_factory(voice_factory)
    set_recommendation_service_factory(recommendation_factory)
    set_chat_service_factory(chat_factory)
    set_tutor_service_factory(tutor_factory)
    # `count`, not the provider names: the logging allow-list exists so that a
    # new field is a deliberate act, and a count answers the only question
    # this line is asked ("did any recogniser get configured?").
    logger.info("services_wired", count=len(asr.provider_names))


__all__ = ["build_asr_chain", "build_gateway", "install_service_factories"]
