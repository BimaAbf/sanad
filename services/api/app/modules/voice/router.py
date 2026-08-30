"""Voice routes. docs/05 §6.

A note on authorisation, because this module is the one exception in the API and
an unexplained exception is how a hole gets left open.

`tools/guards/route_authorisation.py` requires every route with a `{child_id}`
**path parameter** to declare `require_child_access`. These paths have none —
docs/05 §6 fixes them as `/voice/attempt` and `/voice/override`, and renaming
them to `/children/{child_id}/voice/...` would put the API out of step with its
own contract. So the check is made explicitly, in the first statement of each
handler, against a `child_id` carried in the body. The guard cannot see it; the
test `test_voice_routes_authorise_explicitly` can, and does.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import ServiceUnavailable
from app.modules.identity.deps import CurrentCaregiver, IdentityServiceDep
from app.modules.identity.domain import Role
from app.modules.voice.domain.audio import MAX_UPLOAD_BYTES
from app.modules.voice.domain.scoring import ExpectedWord
from app.modules.voice.schemas import (
    AttemptResponse,
    OverrideRequest,
    OverrideResponse,
    VoiceHealth,
)
from app.modules.voice.service import AudioInvalid, VoiceService

router = APIRouter(prefix="/voice", tags=["voice"])

VoiceServiceFactory = Callable[[AsyncSession], VoiceService]

#: Set at wiring time. A module-level hook so unit tests can drive the routes
#: without a database, exactly as the identity module does for its SMS provider.
_service_factory: VoiceServiceFactory | None = None


def set_voice_service_factory(factory: VoiceServiceFactory | None) -> None:
    global _service_factory
    _service_factory = factory


async def get_voice_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AsyncIterator[VoiceService]:
    if _service_factory is None:
        # Not a 404: the routes exist, the dependency does not. A deployment
        # without a voice tier should say so rather than pretend the endpoint
        # was never there.
        raise ServiceUnavailable(detail="Voice service is not configured in this deployment.")
    yield _service_factory(session)


@router.post("/attempt", response_model=AttemptResponse)
async def post_attempt(
    caregiver_id: CurrentCaregiver,
    identity: IdentityServiceDep,
    service: Annotated[VoiceService, Depends(get_voice_service)],
    child_id: Annotated[UUID, Form()],
    activity_id: Annotated[UUID, Form()],
    skill_code: Annotated[str, Form()],
    label_ar: Annotated[str, Form()],
    audio: Annotated[UploadFile, File()],
    label_egy: Annotated[str, Form()] = "",
    attempt_no: Annotated[int, Form()] = 1,
) -> AttemptResponse:
    await identity.assert_child_access(
        caregiver_id=caregiver_id, child_id=child_id, min_role=Role.CO_CAREGIVER
    )

    # Read one byte more than the limit, so an oversized upload is rejected
    # without the whole of it ever being resident.
    data = await audio.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise AudioInvalid(detail="audio_too_large", extra={"reason": "audio_too_large"})

    outcome = await service.score_attempt(
        child_id=str(child_id),
        expected=ExpectedWord(
            skill_code=skill_code, label_ar=label_ar, label_egy=label_egy or label_ar
        ),
        audio=data,
        attempt_no=attempt_no,
        attempt_id=str(uuid4()),
    )
    return AttemptResponse(
        verdict=outcome.score.verdict.value,
        similarity=round(outcome.score.similarity, 3),
        heard=outcome.score.heard,
        mode=outcome.mode.value,
    )


@router.post("/override", response_model=OverrideResponse)
async def post_override(
    body: OverrideRequest,
    caregiver_id: CurrentCaregiver,
    identity: IdentityServiceDep,
    service: Annotated[VoiceService, Depends(get_voice_service)],
) -> OverrideResponse:
    await identity.assert_child_access(
        caregiver_id=caregiver_id, child_id=body.child_id, min_role=Role.CO_CAREGIVER
    )
    await service.override(
        child_id=str(body.child_id),
        expected=ExpectedWord(
            skill_code=body.skill_code, label_ar=body.skill_code, label_egy=body.skill_code
        ),
    )
    return OverrideResponse(recorded=True)


@router.get("/health", response_model=VoiceHealth)
async def voice_health(
    service: Annotated[VoiceService, Depends(get_voice_service)],
) -> VoiceHealth:
    """Provider reachability and corpus completeness.

    Names providers and counts, and reveals nothing about any child — which is
    what makes it safe to expose to a load balancer.
    """
    return VoiceHealth(
        providers=service.provider_status(),
        cache_hit_rate=service.cache_hit_rate(),
        missing_assets=service.missing_asset_count(),
    )
