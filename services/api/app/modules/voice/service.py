"""The voice attempt flow.

Reading order, because the order of these steps is the privacy design:

    validate bytes  →  require consent  →  transcribe  →  score  →  delete audio

Deletion is in a `finally`. There is no path through this module — not an ASR
timeout, not a scoring exception, not a caller that forgets — on which a child's
audio outlives the request without `voice_retention` consent. docs/04d §5 states
the rule; putting it anywhere other than a `finally` would make it a convention.

The other rule this module enforces by construction: **nothing here touches the
LLM gateway.** Audio, transcripts and embeddings never cross that boundary, and
the enforcement is that `app.ai` is not imported anywhere in `app.modules.voice`
— asserted by a test, because a comment is not enforcement.
"""

from __future__ import annotations

import datetime as dt
import os
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

import structlog

from app.core.errors import BadRequest, Forbidden
from app.modules.children.domain import ConsentKey
from app.modules.voice.domain.audio import (
    AudioRejected,
    needs_temp_file,
    validate_upload,
)
from app.modules.voice.domain.modes import VoiceCapability, VoiceMode, bkt_inputs
from app.modules.voice.domain.normalize import normalize_ar
from app.modules.voice.domain.scoring import (
    AttemptResult,
    ExpectedWord,
    Score,
    caregiver_override,
    score_attempt,
)
from app.modules.voice.providers import AsrChain

logger = structlog.get_logger(__name__)

#: docs/04d §5 — consented audio lives 30 days, then the lifecycle rule removes it.
RETENTION_DAYS = 30

#: docs/04d §3 — at most this many confirmed utterances per skill are kept for
#: the per-child reference model. Beyond that the marginal value is nil and the
#: only thing still growing is the amount of a child's voice we are holding.
MAX_REFERENCES_PER_SKILL = 20


class AudioNotPermitted(Forbidden):
    code = "voice_consent_required"
    title = "Voice Consent Required"
    message_ar = "محتاجين موافقتك على استخدام الميكروفون الأول."


class AudioInvalid(BadRequest):
    code = "audio_rejected"
    title = "Audio Rejected"
    message_ar = "الصوت مش وصل صح. جرّبوا تاني."


class AudioSink(Protocol):
    """Where consented audio goes. S3/R2 in deployment, memory in tests."""

    async def put(self, key: str, data: bytes, *, content_type: str) -> str: ...

    async def purge_prefix(self, prefix: str) -> int: ...

    async def list_prefix(self, prefix: str) -> list[str]: ...


class InMemoryAudioSink:
    """Test double, and the shape the real one must match."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.content_types: dict[str, str] = {}

    async def put(self, key: str, data: bytes, *, content_type: str) -> str:
        self.objects[key] = data
        self.content_types[key] = content_type
        return key

    async def purge_prefix(self, prefix: str) -> int:
        keys = [key for key in self.objects if key.startswith(prefix)]
        for key in keys:
            del self.objects[key]
            self.content_types.pop(key, None)
        return len(keys)

    async def list_prefix(self, prefix: str) -> list[str]:
        return sorted(key for key in self.objects if key.startswith(prefix))


class ConsentReader(Protocol):
    async def is_granted(self, child_id: str, key: ConsentKey) -> bool: ...


@dataclass(frozen=True, slots=True)
class VoiceOutcome:
    """Everything the caller needs, and nothing the child should not see."""

    score: Score
    mode: VoiceMode
    #: (correct, prompt_level, discount_override) — ready for `bkt_update`.
    bkt: tuple[bool, object, float | None] | None
    stored_audio_key: str | None = None
    provider: str = "none"
    #: Set when the activity should switch modes for the rest of the session.
    degraded_to: VoiceMode | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)


def phrase_hints(expected: ExpectedWord, variants: Sequence[str] = ()) -> list[str]:
    """The expected word, its colloquial form, and known child variants.

    Deduplicated and ordered so the list is stable — a provider that caches on
    the hint string should see the same string for the same skill every time.
    """
    candidates = [expected.label_ar, expected.label_egy, *variants]
    seen: dict[str, None] = {}
    for candidate in candidates:
        normalised = normalize_ar(candidate)
        if normalised:
            seen.setdefault(normalised, None)
    return list(seen)


def audio_key(child_id: str, skill_code: str, attempt_id: str) -> str:
    """docs/04d §5 — `audio/{child_id}/{skill}/{uuid}.opus`."""
    return f"audio/{child_id}/{skill_code}/{attempt_id}.opus"


class TempAudio:
    """Holds the upload for the life of one scoring call, then removes it.

    Small uploads never touch the disk at all (docs/04d §5: a temp file only
    above 256 KB). `path` is None in that case, and `cleanup` is still safe to
    call — a caller must not have to know which branch it took.
    """

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.path: str | None = None
        if needs_temp_file(data):
            handle, path = tempfile.mkstemp(prefix="misk-voice-", suffix=".audio")
            with os.fdopen(handle, "wb") as file:
                file.write(data)
            self.path = path

    def cleanup(self) -> None:
        if self.path is None:
            return
        try:
            os.unlink(self.path)
        except FileNotFoundError:  # pragma: no cover - already gone is success
            pass
        finally:
            self.path = None


class VoiceService:
    def __init__(
        self,
        *,
        asr: AsrChain,
        consent: ConsentReader,
        sink: AudioSink,
        now: dt.datetime | None = None,
        missing_assets: int = 0,
    ) -> None:
        self._asr = asr
        self._consent = consent
        self._sink = sink
        self._now = now
        self._missing_assets = missing_assets

    # --- health -------------------------------------------------------------

    def provider_status(self) -> dict[str, str]:
        """Which recognisers are configured, in failover order.

        Reports configuration, not a live probe: probing a scale-to-zero GPU on
        every health check would keep it awake and turn a $0 idle tier into a
        billed one.
        """
        return dict.fromkeys(self._asr.provider_names, "configured")

    def cache_hit_rate(self) -> float:
        """1.0 by construction after docs/12 §Δ2.

        There is no runtime TTS provider left to miss against — every clip the
        child hears is a static file. The field stays in the response because
        docs/05 §6 defines it and a client reads it; it is honest about being a
        constant rather than being quietly removed.
        """
        return 1.0

    def missing_asset_count(self) -> int:
        """Gaps in the rendered corpus. Non-zero blocks a content publish.

        Wired to the renderer's report in P15; until that report exists this
        returns 0 rather than guessing, and `tools/voice_render/report.py` is
        the thing that actually fails a publish.
        """
        return self._missing_assets

    async def capability(
        self,
        child_id: str,
        *,
        mic_permission: bool = True,
        asr_providers_up: int = 1,
        caregiver_present: bool = True,
        noisy_environment: bool = False,
    ) -> VoiceCapability:
        from app.modules.voice.domain.modes import resolve_capability

        return resolve_capability(
            voice_asr_consent=await self._consent.is_granted(child_id, ConsentKey.VOICE_ASR),
            mic_permission=mic_permission,
            asr_providers_up=asr_providers_up,
            caregiver_present=caregiver_present,
            noisy_environment=noisy_environment,
        )

    async def score_attempt(
        self,
        *,
        child_id: str,
        expected: ExpectedWord,
        audio: bytes,
        attempt_no: int,
        attempt_id: str,
        known_variants: Sequence[str] = (),
    ) -> VoiceOutcome:
        """Transcribe, score, and get rid of the audio.

        Consent is checked before the bytes are looked at in any way that could
        leave a trace, and the ASR provider is never called without it.
        """
        if not await self._consent.is_granted(child_id, ConsentKey.VOICE_ASR):
            raise AudioNotPermitted(detail="voice_asr consent is not granted")

        try:
            container = validate_upload(audio)
        except AudioRejected as exc:
            raise AudioInvalid(detail=exc.reason, extra={"reason": exc.reason}) from exc

        retain = await self._consent.is_granted(child_id, ConsentKey.VOICE_RETENTION)
        held = TempAudio(audio)
        stored_key: str | None = None
        try:
            result = await self._asr.transcribe(
                held.data, phrase_hints=phrase_hints(expected, known_variants)
            )
            score = score_attempt(expected, result, attempt_no=attempt_no)

            if retain and score.result is not None:
                stored_key = await self._sink.put(
                    audio_key(child_id, expected.skill_code, attempt_id),
                    held.data,
                    content_type=container.mime,
                )
        finally:
            # Unconditional. See the module docstring.
            held.cleanup()

        mode = VoiceMode.ASR if not result.unavailable else VoiceMode.CAREGIVER_CONFIRM
        logger.info(
            "voice_attempt_scored",
            child_id=child_id,
            skill=expected.skill_code,
            verdict=score.verdict.value,
            attempt_no=attempt_no,
            provider=result.provider,
            retained=stored_key is not None,
        )
        return VoiceOutcome(
            score=score,
            mode=mode,
            bkt=bkt_inputs(score.result) if score.result is not None else None,
            stored_audio_key=stored_key,
            provider=result.provider,
            degraded_to=VoiceMode.CAREGIVER_CONFIRM if result.unavailable else None,
            notes=(score.reason,),
        )

    async def override(self, *, child_id: str, expected: ExpectedWord) -> VoiceOutcome:
        """The caregiver tapped "قالها صح ✅".

        Needs no consent and no provider: nothing is recorded but the fact that
        an adult in the room said the child got it right. That is why this path
        is the one that always works.
        """
        score = caregiver_override()
        logger.info("voice_caregiver_override", child_id=child_id, skill=expected.skill_code)
        return VoiceOutcome(
            score=score,
            mode=VoiceMode.CAREGIVER_CONFIRM,
            bkt=bkt_inputs(AttemptResult.CAREGIVER_CONFIRMED),
            provider="caregiver",
        )

    async def purge_child_audio(self, child_id: str) -> int:
        """Withdrawal of `voice_retention`. docs/04d §5 gives this 5 minutes.

        Returns the number of objects removed. The pgvector reference rows are
        deleted by the caller in the same transaction — this method owns the
        object store only, so that a storage failure cannot leave the database
        claiming references that no longer exist.
        """
        removed = await self._sink.purge_prefix(f"audio/{child_id}/")
        logger.info("voice_audio_purged", child_id=child_id, objects=removed)
        return removed
