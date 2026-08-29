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
            "session_minutes": self.session_minutes,
            "fatigue": self.fatigue,
        }


@dataclass(frozen=True, slots=True)
class GuardedBrainDecision:
    proposed: BrainDecision
    final: BrainDecision
    actions: tuple[str, ...] = ()


SUPPORTED_ACTIVITY_TYPES = frozenset({"count_objects", "listen_point", "match", "identify"})
SUPPORTED_MODALITIES = frozenset({"visual", "audio", "receptive", "expressive", "productive"})
MAX_DIFFICULTY_JUMP = 1
MAX_REPEAT_STREAK = 3


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
        difficulty=max(1, min(5, 1 if struggling else 2)),
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
        activity_type="listen_point",
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
        final = final.model_copy(update={"activity_type": "listen_point"})
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
