"""The live half of the AI Brain: one bounded call, through the one gateway.

Everything about the teaching decision that is *intelligence* happens here, and
everything that is *truth* happens somewhere else. The model receives evidence
and a candidate set and returns a `BrainDecision`; it cannot see a child's name,
it cannot compute mastery, and it cannot name a skill that is not in the set it
was given — the last two because `BrainDecision` has no field for the first and
`guard_decision` rejects the second.

`propose` never raises and never blocks a session. Every failure the gateway
can report — no key, no fixture, a timeout, a refusal, a schema mismatch, a
provider error — comes back as `None`, and the caller runs the deterministic
decision instead. That is the AI OFF path, and it is the default configuration
rather than a degraded one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import structlog

from app.ai.gateway import LlmGateway, Outcome
from app.modules.learning.domain.candidates import Candidate
from app.modules.tutor_ai.brain import BrainDecision, LearnerEvidence, build_request

logger = structlog.get_logger(__name__)

DECISION_POINT = "tutor_brain"

#: What the fallback is called on the decision row and in the AI inspector.
#: Named rather than hidden: a caregiver-facing claim that SANAD adapted has to
#: be distinguishable from a deterministic rule that did the same thing.
FALLBACK_MODEL = "deterministic_fallback"

#: The frozen prefix. Everything here is identical on every call, which is what
#: makes prompt caching hit — `tools/guards/prompt_cache_hit.py` fails the build
#: if it stops hitting. Nothing child-specific may move into this block.
SYSTEM_FROZEN: tuple[dict[str, Any], ...] = (
    {
        "type": "text",
        "text": (
            "You choose how to teach the next activity to one child with Down "
            "syndrome, learning in Egyptian Arabic.\n"
            "\n"
            "You decide teaching strategy only. You do NOT decide whether the "
            "child was right, what they have mastered, or what their score is. "
            "Those are computed elsewhere from what the child actually did, and "
            "nothing you return can change them.\n"
            "\n"
            "Choose next_skill from the candidate list you are given and from "
            "nowhere else. Every other field is a closed set; a value outside "
            "it is discarded and replaced.\n"
            "\n"
            "Principles, in priority order:\n"
            "1. Errorless learning. When recent evidence is weak, lower the "
            "difficulty and raise the support before asking again.\n"
            "2. Use what has worked for THIS child. If demonstrations have "
            "preceded their successes, demonstrate. If a modality has a higher "
            "success rate, prefer it.\n"
            "3. Change one thing at a time. Two failures do not justify moving "
            "skill, difficulty, modality and strategy at once.\n"
            "4. Finish on something the child can do.\n"
            "\n"
            "reason_codes are SHORT_UPPER_SNAKE identifiers naming the evidence "
            "you used, at most eight. They are shown to a caregiver as the "
            "explanation for what happened. Do not put reasoning, diagnosis, or "
            "any sentence about the child into them."
        ),
    },
)


@dataclass(frozen=True, slots=True)
class Proposal:
    """What the model said, and what happened when we asked."""

    decision: BrainDecision | None
    #: The gateway outcome name — `ok`, `no_fixture`, `timeout`, `refusal`,
    #: `schema_error`, `provider_error`, `budget_exceeded`, `flag_off`.
    outcome: str
    model_name: str
    latency_ms: int = 0

    @property
    def used_ai(self) -> bool:
        return self.decision is not None


async def propose(
    gateway: LlmGateway,
    *,
    candidates: Sequence[Candidate],
    evidence: LearnerEvidence,
    child_id: str,
    correlation_id: str = "",
) -> Proposal:
    """Ask for a teaching decision. Returns a `Proposal`, never raises."""
    if not candidates:
        # Nothing to choose between. Asking anyway would spend a call to be told
        # something we already know, and would give the model an empty candidate
        # set to hallucinate into.
        return Proposal(None, "no_candidates", FALLBACK_MODEL)

    try:
        result = await gateway.call_structured(
            decision_point=DECISION_POINT,
            schema_model=BrainDecision,
            system_frozen=SYSTEM_FROZEN,
            child_context={
                # Bands and rates, never a name, a birth date or a diagnosis.
                # `Pseudonymiser` scrubs on the way out as well; this is the
                # first of the two, and it is the one that means there was never
                # an unredacted payload to scrub.
                "learner_support": evidence.recent_strategies[-3:],
                "modality_accuracy": dict(evidence.modality_accuracy),
                "session_minutes": evidence.session_minutes,
            },
            volatile=build_request(candidates, evidence),
            child_id=child_id,
            correlation_id=correlation_id,
        )
    except Exception as exc:  # noqa: BLE001 -- see below
        # Deliberately blind, for the reason `gateway.call_structured` gives
        # for its own: a session must not 500 because a model call raised
        # something nobody listed. The child gets the deterministic decision,
        # which is a good decision.
        logger.info("tutor_brain_call_failed", exc_type=type(exc).__name__)
        return Proposal(None, "call_failed", FALLBACK_MODEL)

    model = f"{gateway.provider.value}:live" if result.outcome is Outcome.OK else FALLBACK_MODEL
    if result.outcome is not Outcome.OK:
        logger.info("tutor_brain_fallback", outcome=result.outcome.value)
    return Proposal(
        decision=result.value,
        outcome=result.outcome.value,
        model_name=model,
        latency_ms=result.latency_ms,
    )


__all__ = ["DECISION_POINT", "FALLBACK_MODEL", "SYSTEM_FROZEN", "Proposal", "propose"]
