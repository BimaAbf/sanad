"""DP2 — the next-best-exercise judge.

**What the model is and is not allowed to do here.** The deterministic engine
(`learning/domain/candidates.py`) produces the candidate set: it applies the
clinical composition rule -- at most one new skill per session, none at all
while three or more are still `practising` -- and it produces a default order.
The judge may **reorder that set and pick a head from it**. It may never add an
item, never invent a skill id, and never introduce a second new skill. Those are
not conventions; `enforce_permutation` and `count_new` reject them and the
deterministic order ships instead.

This is why the judge is worth having at all despite the constraint. The engine
knows what is *due*. It does not know that this child has confused red with
orange four times running, that their last two sessions ended in fatigue at
minute six, or that the one skill they are proud of is the one to open on today.
The retrieval corpus knows all three, and reordering on that basis is a real
improvement that carries no clinical risk, because every ordering the judge can
produce was already approved by the engine.

The fallback is not a degraded mode. If the model is unavailable, refuses,
returns the wrong shape or names a skill that is not in the set, the engine's
own order ships and the caregiver sees a working recommendation. That property
is exercised directly by a chaos test rather than argued for.

Pure. The model call lives in `graph.py`; everything here is data in, data out.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.guardrails.chain import CandidateSetLayer, GuardrailChain, SchemaLayer
from app.guardrails.layers import (
    GuardrailEvent,
    GuardrailRejection,
    enforce_permutation,
    enforce_reading_level,
)
from app.modules.learning.domain.candidates import Candidate, CandidateKind, count_new

DECISION_POINT = "tutor_plan"

#: Declared for `tools/guards/required_guardrail_layer.py`, which fails the
#: build if a decision point that selects from a set does not declare
#: `CandidateSetLayer`. Data, not a comment, so the guard can read it.
DECLARED_LAYERS: tuple[type, ...] = (SchemaLayer, CandidateSetLayer)

#: The engine never returns more than eight candidates, and a plan longer than
#: the engine's own set is definitionally not a permutation of a subset of it.
MAX_PLAN_LENGTH = 8

#: docs/04c §C07 — at most one new skill per session, enforced after the fact.
MAX_NEW_IN_PLAN = 1


class NextExercisePlan(BaseModel):
    """The judge's output contract.

    `extra="forbid"` is the L2 schema layer: a model that adds a field is a
    model that has decided to tell us something we did not ask for, and the
    right response is to reject the whole answer rather than to ignore the
    extra key.
    """

    model_config = ConfigDict(extra="forbid")

    #: Skill ids from the candidate set, best first. A subset is allowed --
    #: a judge that drops a candidate it thinks is wrong for today is doing its
    #: job -- but the head of this list is what the caregiver is shown next.
    ordered_skill_ids: list[str] = Field(min_length=1, max_length=MAX_PLAN_LENGTH)
    #: One short Arabic sentence for the caregiver. Guardrailed for reading
    #: level and clinical safety before it is ever rendered.
    reason_ar: str = Field(min_length=1, max_length=240)
    #: How much of the ordering came from retrieved history rather than from the
    #: engine's default. Reported, never acted on -- it exists so the console can
    #: show whether the model is actually contributing anything.
    grounded_in: list[str] = Field(default_factory=list, max_length=8)


@dataclass(frozen=True, slots=True)
class Recommendation:
    """What the service returns, whichever path produced it."""

    skill_id: str
    skill_code: str
    label_ar: str
    kind: str
    ordered_skill_ids: tuple[str, ...]
    reason_ar: str
    source: Literal["ai", "deterministic_fallback"]
    grounded_in: tuple[str, ...] = ()
    events: tuple[GuardrailEvent, ...] = field(default_factory=tuple)


#: docs/04a: the caregiver never sees a mastery percentage, so the fallback
#: sentence never contains one either. One sentence, plain register.
FALLBACK_REASON_AR = "دي أقرب مهارة جاهزة للمراجعة النهارده."

KIND_REASON_AR: dict[CandidateKind, str] = {
    CandidateKind.LAPSED: "المهارة دي محتاجة رجوع ليها.",
    CandidateKind.DUE: "دي أقرب مهارة جاهزة للمراجعة النهارده.",
    CandidateKind.NEW: "مهارة جديدة، والوقت مناسب ليها.",
    CandidateKind.CONFIDENCE: "مهارة بيعرفها كويس، عشان نبدأ بمكسب.",
}


def candidate_ids(candidates: Sequence[Candidate]) -> list[str]:
    return [candidate.skill_id for candidate in candidates]


def build_chain(candidates: Sequence[Candidate]) -> GuardrailChain:
    """The checks a judge answer must pass, cheapest first.

    Order is the design. Membership is a set operation over eight items and runs
    before the reading-level regex; the new-skill count runs last because it has
    to resolve every id back to its candidate to know its kind.
    """
    allowed = candidate_ids(candidates)
    by_id = {candidate.skill_id: candidate for candidate in candidates}

    def permutation(plan: NextExercisePlan) -> None:
        enforce_permutation(plan.ordered_skill_ids, allowed)

    def reading_level(plan: NextExercisePlan) -> None:
        enforce_reading_level(plan.reason_ar)

    def new_skill_budget(plan: NextExercisePlan) -> None:
        selected = [by_id[skill_id] for skill_id in plan.ordered_skill_ids]
        introduced = count_new(selected)
        if introduced > MAX_NEW_IN_PLAN:
            # Not a style violation. Two new skills in one session is the
            # interference-and-frustration failure docs/04c §C06 exists to
            # prevent, and the engine already guaranteed at most one -- so
            # reaching here means the plan is not a subset of what was offered.
            raise GuardrailRejection(
                "new_skill_budget",
                {"introduced": introduced, "max": MAX_NEW_IN_PLAN},
            )

    return GuardrailChain(
        DECISION_POINT,
        [
            ("candidate_permutation", permutation),
            ("reading_level", reading_level),
            ("new_skill_budget", new_skill_budget),
        ],
    )


def deterministic_recommendation(
    candidates: Sequence[Candidate],
    labels: Mapping[str, tuple[str, str]],
    *,
    events: Sequence[GuardrailEvent] = (),
) -> Recommendation | None:
    """The engine's own answer. The floor under every AI path.

    `labels` maps skill id -> (code, Arabic label). A candidate with no label is
    dropped rather than rendered with its uuid: a caregiver shown a uuid has
    been shown a bug, and the next candidate is a perfectly good answer.
    """
    for candidate in candidates:
        label = labels.get(candidate.skill_id)
        if label is None:
            continue
        code, label_ar = label
        return Recommendation(
            skill_id=candidate.skill_id,
            skill_code=code,
            label_ar=label_ar,
            kind=candidate.kind.value,
            ordered_skill_ids=tuple(candidate_ids(candidates)),
            reason_ar=KIND_REASON_AR.get(candidate.kind, FALLBACK_REASON_AR),
            source="deterministic_fallback",
            events=tuple(events),
        )
    return None


def apply(
    plan: NextExercisePlan | None,
    candidates: Sequence[Candidate],
    labels: Mapping[str, tuple[str, str]],
) -> Recommendation | None:
    """Take the judge's plan if it survives the chain; otherwise the engine's.

    A `None` plan is the ordinary case, not an error path -- it is what the
    gateway returns for a missing fixture, an exhausted budget, a refusal, a
    timeout and a schema mismatch alike. All five land here and all five produce
    the engine's answer.
    """
    if plan is None:
        return deterministic_recommendation(candidates, labels)

    result = build_chain(candidates).run(plan)
    if not result.ok:
        return deterministic_recommendation(candidates, labels, events=result.events)

    by_id = {candidate.skill_id: candidate for candidate in candidates}
    for skill_id in plan.ordered_skill_ids:
        label = labels.get(skill_id)
        if label is None:
            continue
        code, label_ar = label
        return Recommendation(
            skill_id=skill_id,
            skill_code=code,
            label_ar=label_ar,
            kind=by_id[skill_id].kind.value,
            ordered_skill_ids=tuple(plan.ordered_skill_ids),
            reason_ar=plan.reason_ar,
            source="ai",
            grounded_in=tuple(plan.grounded_in),
            events=tuple(result.events),
        )
    return deterministic_recommendation(candidates, labels, events=result.events)


def volatile_payload(
    candidates: Sequence[Candidate],
    labels: Mapping[str, tuple[str, str]],
    documents: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """This turn's half of the prompt.

    The candidate set is sent with its `kind` and `priority` intact. Hiding the
    engine's own ordering and then asking the model to produce one would be
    asking it to guess at a rule it is not allowed to break -- and the reordering
    we want from it is a refinement of that order, not a replacement for it.
    """
    return {
        "candidates": [
            {
                "skill_id": candidate.skill_id,
                "label_ar": labels.get(candidate.skill_id, ("", ""))[1],
                "kind": candidate.kind.value,
                "engine_priority": candidate.priority,
                "modality": candidate.modality,
            }
            for candidate in candidates
        ],
        "history": list(documents),
    }


__all__ = [
    "DECISION_POINT",
    "DECLARED_LAYERS",
    "FALLBACK_REASON_AR",
    "MAX_NEW_IN_PLAN",
    "MAX_PLAN_LENGTH",
    "NextExercisePlan",
    "Recommendation",
    "apply",
    "build_chain",
    "candidate_ids",
    "deterministic_recommendation",
    "volatile_payload",
]
