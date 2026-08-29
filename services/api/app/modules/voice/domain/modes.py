"""What the expressive path degrades to, and when.

Three layers, each of which works with one fewer dependency than the last
(docs/04d §7 and docs/12 §3.3):

    ASR (Qwen) → ASR (Groq Whisper) → caregiver confirmation → say-it-together

The last one needs no vendor at all, which is the point. And beneath all of
them sits the consent question: without `voice_asr` the expressive path does not
exist, and the curriculum has to be completable without it.

Pure. No I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.modules.learning.domain.bkt import PromptLevel
from app.modules.voice.domain.scoring import AttemptResult

#: docs/04d §3: a caregiver override is worth half an independent correct.
CAREGIVER_CONFIRMED_DISCOUNT = 0.5


class VoiceMode(StrEnum):
    #: A recogniser answered. Normal scoring.
    ASR = "asr"
    #: No recogniser. The model audio plays; the caregiver taps "قالها صح ✅".
    CAREGIVER_CONFIRM = "caregiver_confirm"
    #: No recogniser and no confirmation available — the activity becomes a
    #: shared "say it together" moment, which is still a real teaching act.
    SAY_TOGETHER = "say_together"
    #: `voice_asr` not granted, or the microphone was refused. Expressive
    #: activities are replaced by their receptive equivalents for the session.
    RECEPTIVE_ONLY = "receptive_only"


@dataclass(frozen=True, slots=True)
class VoiceCapability:
    """What this session may do, resolved once at session start."""

    mode: VoiceMode
    #: Shown to the caregiver as a one-line explainer. Never shown to the child.
    reason: str = ""

    @property
    def expressive_allowed(self) -> bool:
        return self.mode is not VoiceMode.RECEPTIVE_ONLY

    @property
    def records_audio(self) -> bool:
        return self.mode is VoiceMode.ASR


def resolve_capability(
    *,
    voice_asr_consent: bool,
    mic_permission: bool,
    asr_providers_up: int,
    caregiver_present: bool = True,
    noisy_environment: bool = False,
) -> VoiceCapability:
    """The single place the degradation ladder is decided.

    Consent is checked first and unconditionally: a provider being healthy can
    never make a missing consent irrelevant, and ordering the checks the other
    way round is exactly how that bug gets written.
    """
    if not voice_asr_consent:
        return VoiceCapability(VoiceMode.RECEPTIVE_ONLY, "consent_voice_asr_absent")
    if not mic_permission:
        return VoiceCapability(VoiceMode.RECEPTIVE_ONLY, "mic_permission_denied")
    if noisy_environment:
        # Measured client-side as SNR < 5 dB. Suggested once, then this for the
        # rest of the session — repeatedly asking a family to find a quiet room
        # is its own kind of nagging.
        return VoiceCapability(VoiceMode.CAREGIVER_CONFIRM, "environment_too_noisy")
    if asr_providers_up > 0:
        return VoiceCapability(VoiceMode.ASR, "")
    if caregiver_present:
        return VoiceCapability(VoiceMode.CAREGIVER_CONFIRM, "asr_unavailable")
    return VoiceCapability(VoiceMode.SAY_TOGETHER, "asr_unavailable_no_caregiver")


def bkt_inputs(result: AttemptResult) -> tuple[bool, PromptLevel, float | None]:
    """(correct, prompt_level, discount_override) for one voice result.

    `accepted_on_effort` is recorded at `partial_verbal` because docs/04d §3
    says it should behave like one: the child was given the model before the
    second attempt, so the response carries prompted-level evidence, not
    independent evidence.
    """
    if result is AttemptResult.CORRECT:
        return True, PromptLevel.INDEPENDENT, None
    if result is AttemptResult.ACCEPTED_ON_EFFORT:
        return True, PromptLevel.PARTIAL_VERBAL, None
    if result is AttemptResult.CAREGIVER_CONFIRMED:
        return True, PromptLevel.INDEPENDENT, CAREGIVER_CONFIRMED_DISCOUNT
    return False, PromptLevel.INDEPENDENT, None
