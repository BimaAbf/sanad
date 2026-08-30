"""Structured tutor brain orchestration.

The brain recommends teaching strategy; deterministic learning code owns mastery.
This module is deliberately provider-neutral so fixtures, live providers, and
provider failures all pass through the same schema and guardrails.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.learning.domain.candidates import Candidate, CandidateKind
from app.modules.tutor.domain.contract import ActivityType
from app.modules.tutor_ai.evidence import EvidenceBundle

# Provider-neutral defaults used by fixture mode and safe recovery.
DEFAULT_THEME = "ألعاب"


class BrainAction(StrEnum):
    CONTINUE = "continue"
    REVIEW = "review"
    ADVANCE = "advance"


class TeachingStrategy(StrEnum):
    DEMONSTRATE_THEN_TEST = "demonstrate_then_test"
    GUIDED_PRACTICE = "guided_practice"
    INDEPENDENT_PRACTICE = "independent_practice"
    SPACED_REVIEW = "spaced_review"


class SupportLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ReviewTiming(StrEnum):
    IMMEDIATE = "immediate"
    LATER_IN_SESSION = "later_in_session"
    NEXT_SESSION = "next_session"
    NONE = "none"


class BrainDecision(BaseModel):
    """Only teaching controls are modelled; mastery is intentionally absent."""

    # Enums stay enums (no use_enum_values): the guard compares members with
    # `is`, and model_dump(mode="json") still serializes them to their values
    # for the audit trail.
    model_config = ConfigDict(extra="forbid")

    next_skill: str = Field(min_length=1, max_length=120)
    action: BrainAction
    difficulty: int = Field(ge=1, le=5)
    strategy: TeachingStrategy
    modality: str = Field(min_length=1, max_length=40)
    support_level: SupportLevel
    demonstrate_first: bool
    repeat: bool
    review_timing: ReviewTiming
    activity_type: str = Field(min_length=1, max_length=80)
    theme: str = Field(min_length=1, max_length=80)
    character: Literal["mano", "kira"]
    behavior: Literal["demonstrate", "encourage", "prompt", "celebrate"]
    emotion: Literal["encouraging", "calm", "curious", "proud"]
    reason_codes: list[str] = Field(min_length=1, max_length=8)

    @field_validator("reason_codes")
    @classmethod
    def codes_are_auditable(cls, values: list[str]) -> list[str]:
        if any(not code.replace("_", "").isalnum() or len(code) > 50 for code in values):
            raise ValueError("reason_codes must be concise identifiers")
        return values


@dataclass(frozen=True, slots=True)
class LearnerEvidence:
    """Provider-safe snapshot of current evidence, without child identity."""

    skill: str
    modality: str
    p_known: float
    initial_assessment: float | None = None
    recent_results: tuple[str, ...] = ()
    prompt_levels: tuple[str, ...] = ()
    hints: int = 0
    retries: int = 0
    response_times_ms: tuple[int, ...] = ()
    modality_accuracy: Mapping[str, float] = field(default_factory=dict)
    demonstration_accuracy: float | None = None
    speech_accuracy: float | None = None
    retention: float | None = None
    recent_strategies: tuple[str, ...] = ()
    #: The activity types this child has most recently been given, oldest
    #: first. Used to vary what is asked, which is a teaching decision and not
    #: a cosmetic one: three matching tasks in a row is not practice.
    recent_activity_types: tuple[str, ...] = ()
    #: What the runtime says can actually be delivered for the candidate skill
    #: right now — category support, a tracing reference, a granted microphone.
    #: Empty means "the caller did not narrow it", and the full set is assumed.
    available_activity_types: tuple[str, ...] = ()
    session_minutes: int = 0
    fatigue: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "modality": self.modality,
            "p_known": round(self.p_known, 4),
            "initial_assessment": self.initial_assessment,
            "recent_results": list(self.recent_results),
            "prompt_levels": list(self.prompt_levels),
            "hints": self.hints,
            "retries": self.retries,
            "response_times_ms": list(self.response_times_ms),
            "modality_accuracy": dict(self.modality_accuracy),
            "demonstration_accuracy": self.demonstration_accuracy,
            "speech_accuracy": self.speech_accuracy,
            "retention": self.retention,
            "recent_strategies": list(self.recent_strategies),
            "recent_activity_types": list(self.recent_activity_types),
            "available_activity_types": list(self.available_activity_types),
            "session_minutes": self.session_minutes,
            "fatigue": self.fatigue,
        }


@dataclass(frozen=True, slots=True)
class GuardedBrainDecision:
    proposed: BrainDecision
    final: BrainDecision
    actions: tuple[str, ...] = ()


#: The closed set of activity types the runtime can actually deliver, taken from
#: the contract rather than restated here. Restating it is how the two drift:
#: this file used to name four types ("count_objects", "listen_point", "match",
#: "identify") of which the tutor implements one, so the deterministic fallback
#: itself tripped the `unsupported_activity_corrected` guardrail on every single
#: decision -- a guard firing on its own default is a guard that tells you
#: nothing.
SUPPORTED_ACTIVITY_TYPES = frozenset(str(value) for value in ActivityType)
SUPPORTED_MODALITIES = frozenset({"visual", "audio", "receptive", "expressive", "productive"})
MAX_DIFFICULTY_JUMP = 1
MAX_REPEAT_STREAK = 3


#: p_known thresholds at which the deterministic fallback steps difficulty up.
#: Bounded above at 4: level 5 is a jump the guardrail would cap anyway, and a
#: fallback should not be the thing that asks the hardest question in the
#: product.
DIFFICULTY_STEPS: tuple[tuple[float, int], ...] = (
    (0.75, 2),
    (0.88, 3),
    (1.01, 4),
)


def _difficulty_for(p_known: float, *, struggling: bool) -> int:
    if struggling:
        return 1
    for ceiling, level in DIFFICULTY_STEPS:
        if p_known < ceiling:
            return level
    return 4


#: The accuracy assumed for a teaching modality this child has never been asked
#: in. Mid-scale on purpose: an unmeasured modality should be tried ahead of one
#: measured badly and behind one measured well, which is what a number in the
#: middle produces without a special case.
UNMEASURED_MODALITY_ACCURACY = 0.6


def _choose_activity_type(evidence: LearnerEvidence, *, struggling: bool) -> str:
    """Which kind of activity to ask for. Deterministic, and evidence-driven.

    Three rules, in order:

      1. a struggling child gets the plainest thing the product has — hear a
         word, point at the picture. Novelty is the last thing a child who has
         just got two wrong needs;
      2. otherwise the type just used is ranked last, because three matching
         tasks in a row is not practice;
      3. among the rest, the type whose teaching modality this child does best
         in comes first.

    `available_activity_types` is what the runtime says can actually be
    delivered — the category supports it, a tracing reference exists, the
    microphone is consented. Choosing outside it would be repaired by the
    guardrail on every single decision, and a guard that fires on its own
    default tells you nothing.
    """
    from app.modules.tutor.domain.contract import TEACHING_MODALITY

    available = [
        ActivityType(value)
        for value in (evidence.available_activity_types or tuple(str(t) for t in ActivityType))
        if value in SUPPORTED_ACTIVITY_TYPES
    ]
    if not available:
        return str(ActivityType.SELECT_PICTURE)
    if struggling:
        return str(
            ActivityType.SELECT_PICTURE
            if ActivityType.SELECT_PICTURE in available
            else available[0]
        )

    last = evidence.recent_activity_types[-1] if evidence.recent_activity_types else ""

    def rank(activity_type: ActivityType) -> tuple[int, float, str]:
        modality = TEACHING_MODALITY[activity_type]
        accuracy = evidence.modality_accuracy.get(modality, UNMEASURED_MODALITY_ACCURACY)
        return (1 if str(activity_type) == last else 0, -accuracy, str(activity_type))

    return str(min(available, key=rank))


def _fallback(candidates: Sequence[Candidate], evidence: LearnerEvidence) -> BrainDecision:
    target = next(
        (candidate for candidate in candidates if candidate.modality == evidence.modality),
        None,
    ) or (candidates[0] if candidates else None)
    if target is None:
        raise ValueError("at least one candidate is required")
    struggling = evidence.p_known < 0.6 or evidence.recent_results[-2:].count("incorrect") >= 2
    visual_strong = evidence.modality_accuracy.get("visual", 0.0) >= 0.75
    demonstrate = struggling or (evidence.demonstration_accuracy or 0.0) >= 0.8
    return BrainDecision(
        next_skill=target.skill_id,
        action=BrainAction.REVIEW if struggling else BrainAction.CONTINUE,
        # Difficulty follows the estimate rather than being one of two values.
        # A fallback that only ever says 1 or 2 makes `MAX_DIFFICULTY_JUMP`, the
        # four-choice activities and half of `CHOICES_FOR_DIFFICULTY`
        # unreachable, so the whole difficulty axis stops existing whenever the
        # model is not answering -- which is the default configuration.
        difficulty=_difficulty_for(evidence.p_known, struggling=struggling),
        strategy=(
            TeachingStrategy.DEMONSTRATE_THEN_TEST
            if demonstrate
            else TeachingStrategy.INDEPENDENT_PRACTICE
        ),
        modality="visual" if visual_strong else target.modality,
        support_level=SupportLevel.HIGH if struggling else SupportLevel.LOW,
        demonstrate_first=demonstrate,
        repeat=struggling,
        review_timing=ReviewTiming.IMMEDIATE if struggling else ReviewTiming.NONE,
        # The activity type follows the evidence like everything else here.
        # A struggling child gets the plainest thing the product has -- hear a
        # word, point at it -- and a child who is doing well gets the type that
        # exercises the modality their record says works.
        activity_type=_choose_activity_type(evidence, struggling=struggling),
        theme=DEFAULT_THEME,
        character="mano",
        behavior="demonstrate" if demonstrate else "encourage",
        emotion="calm" if evidence.fatigue else "encouraging",
        reason_codes=(("LOW_MASTERY", "RECENT_ERRORS") if struggling else ("STABLE_PROGRESS",)),
    )


def build_request(candidates: Sequence[Candidate], evidence: LearnerEvidence) -> dict[str, Any]:
    """Build the complete structured request sent to a provider."""
    return {
        "learner_evidence": evidence.to_dict(),
        "candidates": [
            {
                "skill_id": candidate.skill_id,
                "modality": candidate.modality,
                "kind": candidate.kind.value,
                "priority": candidate.priority,
            }
            for candidate in candidates
        ],
    }


def guard_decision(
    proposed: BrainDecision,
    candidates: Sequence[Candidate],
    evidence: LearnerEvidence,
) -> GuardedBrainDecision:
    allowed = {c.skill_id: c for c in candidates}
    actions: list[str] = []
    fallback = _fallback(candidates, evidence)
    if proposed.next_skill not in allowed:
        return GuardedBrainDecision(proposed, fallback, ("unsupported_skill",))
    candidate = allowed[proposed.next_skill]
    final = proposed
    if proposed.modality not in SUPPORTED_MODALITIES or (
        proposed.modality != candidate.modality and proposed.modality != "visual"
    ):
        final = final.model_copy(update={"modality": candidate.modality})
        actions.append("unsupported_modality_corrected")
    if proposed.activity_type not in SUPPORTED_ACTIVITY_TYPES:
        final = final.model_copy(update={"activity_type": str(ActivityType.SELECT_PICTURE)})
        actions.append("unsupported_activity_corrected")
    if candidate.kind is CandidateKind.NEW and proposed.action is BrainAction.ADVANCE:
        final = final.model_copy(update={"action": BrainAction.CONTINUE})
        actions.append("new_skill_cannot_advance")
    if evidence.fatigue and proposed.difficulty > 1:
        final = final.model_copy(
            update={"difficulty": 1, "support_level": SupportLevel.HIGH, "emotion": "calm"}
        )
        actions.append("fatigue_difficulty_capped")
    if (
        evidence.recent_strategies[-MAX_REPEAT_STREAK:]
        and len(set(evidence.recent_strategies[-MAX_REPEAT_STREAK:])) == 1
        and proposed.repeat
    ):
        final = final.model_copy(
            update={"repeat": False, "review_timing": ReviewTiming.NEXT_SESSION}
        )
        actions.append("repeat_streak_bounded")
    return GuardedBrainDecision(proposed, final, tuple(actions))


def decide(
    candidates: Sequence[Candidate],
    evidence: LearnerEvidence,
    proposed: BrainDecision | None = None,
) -> GuardedBrainDecision:
    """Run fixture/fallback brain and the same deterministic guardrails."""
    baseline = _fallback(candidates, evidence)
    return guard_decision(proposed or baseline, candidates, evidence)


def evidence_from_bundle(bundle: EvidenceBundle) -> LearnerEvidence:
    return LearnerEvidence(
        skill=bundle.skill_code,
        modality=bundle.modality,
        p_known=bundle.p_known,
        recent_results=tuple(a.result for a in bundle.attempts),
        prompt_levels=tuple(a.prompt_level for a in bundle.attempts),
        response_times_ms=tuple(a.latency_ms for a in bundle.attempts),
    )


__all__ = [
    "BrainDecision",
    "GuardedBrainDecision",
    "LearnerEvidence",
    "build_request",
    "decide",
    "evidence_from_bundle",
    "guard_decision",
]
