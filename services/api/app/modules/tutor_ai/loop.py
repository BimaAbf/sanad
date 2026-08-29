"""One complete tutor decision step.

This is the seam used by API/session adapters: evidence in, guarded structured
decision out, optional audit persistence. Mastery remains outside this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.modules.learning.domain.candidates import Candidate
from app.modules.tutor_ai.audit import TutorAuditRepository
from app.modules.tutor_ai.brain import BrainDecision, GuardedBrainDecision, LearnerEvidence, decide


@dataclass(frozen=True, slots=True)
class TutorStep:
    decision: GuardedBrainDecision
    decision_id: UUID | None = None


async def run_step(
    *,
    candidates: list[Candidate],
    evidence: LearnerEvidence,
    child_id: UUID | None = None,
    session_id: UUID | None = None,
    audit: TutorAuditRepository | None = None,
    proposed: BrainDecision | None = None,
    model_name: str = "deterministic_fallback",
) -> TutorStep:
    """Run the same guardrails for fixtures and live-provider proposals."""
    guarded = decide(candidates, evidence, proposed)
    decision_id: UUID | None = None
    if audit is not None and child_id is not None:
        decision_id = await audit.record_decision(
            child_id=child_id,
            session_id=session_id,
            state_snapshot=evidence.to_dict(),
            proposed_decision=guarded.proposed.model_dump(mode="json"),
            final_decision=guarded.final.model_dump(mode="json"),
            reason_codes=list(guarded.final.reason_codes),
            guardrail_actions=list(guarded.actions),
            model_name=model_name,
            resulting_activity_id=guarded.final.next_skill,
        )
    return TutorStep(decision=guarded, decision_id=decision_id)


__all__ = ["TutorStep", "run_step"]
