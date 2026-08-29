"""Session planning (DP2) and the constraints the AI plan must satisfy.

The AI receives a candidate set and may **reorder only**. Every constraint below
is enforced after the fact by `PlanConstraintsLayer`; a violation means the
deterministic ordering ships and the caregiver sees no difference beyond the
order of activities.

The constraints are not arbitrary:
  * open and close on a mastered skill — a guaranteed win in the first twenty
    seconds, and a win to finish on
  * the single new skill sits in position 3-5, when attention is highest but the
    child is warmed up
  * never two expressive tasks in a row — expressive is far more effortful
  * never the same skill twice in a row

ONE SPEC CONFLICT, resolved here and recorded in docs/adr/010-tutor-orchestration.md:

    docs/04c §C06 has `candidates()` return AT MOST ONE mastered "confidence"
    item. docs/04c §C07 requires the plan to open on a mastered skill AND close
    on a mastered skill. With one mastered skill and no duplicates allowed,
    those cannot all hold.

Resolved by letting the single mastered skill BOOKEND the session — first and
last, never adjacent. Repeating an already-mastered item is not a burden on the
child; it is a second guaranteed win, which is the point of the rule. The
no-duplicates constraint still applies to everything else, and adjacency is
still forbidden outright.

Pure. No I/O. The AI's contribution here is genuinely small, which is the point:
if the model is unavailable, nothing of value is lost.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from app.guardrails.layers import GuardrailRejection, enforce_permutation
from app.modules.learning.domain.candidates import Candidate, CandidateKind

#: The new skill belongs in this window, 1-indexed and inclusive.
NEW_SKILL_MIN_POSITION = 3
NEW_SKILL_MAX_POSITION = 5


@dataclass(frozen=True, slots=True)
class PlannedActivity:
    skill_id: str
    modality: str
    kind: CandidateKind


def deterministic_plan(candidates: Sequence[Candidate]) -> list[PlannedActivity]:
    """The ordering that ships whenever the AI is unavailable or wrong.

    Built to satisfy every constraint by construction, so it is always a legal
    plan and never needs its own validation pass.
    """
    by_kind: dict[CandidateKind, list[Candidate]] = {}
    for candidate in candidates:
        by_kind.setdefault(candidate.kind, []).append(candidate)

    confidence = by_kind.get(CandidateKind.CONFIDENCE, [])
    new = by_kind.get(CandidateKind.NEW, [])
    middle = [*by_kind.get(CandidateKind.LAPSED, []), *by_kind.get(CandidateKind.DUE, [])]

    ordered: list[Candidate] = []
    # Open on a win when one is available.
    if confidence:
        ordered.append(confidence[0])

    # Place the middle, inserting the new skill into positions 3-5.
    body = list(middle)
    if new:
        # 0-indexed insertion point; position 3 means index 2.
        insert_at = min(max(NEW_SKILL_MIN_POSITION - 1 - len(ordered), 0), len(body))
        body.insert(insert_at, new[0])
    ordered.extend(body)

    # Close on a win. Reuse the opener only if there is nothing else.
    if len(confidence) > 1:
        ordered.append(confidence[1])
    elif confidence and len(ordered) > 1:
        ordered.append(confidence[0])

    ordered = _separate_repeats(ordered)
    return [PlannedActivity(skill_id=c.skill_id, modality=c.modality, kind=c.kind) for c in ordered]


def _separate_repeats(candidates: list[Candidate]) -> list[Candidate]:
    """Push apart back-to-back same-skill and back-to-back expressive items."""
    result: list[Candidate] = []
    pending: list[Candidate] = list(candidates)
    while pending:
        placed = False
        for index, candidate in enumerate(pending):
            if _may_follow(result[-1] if result else None, candidate):
                result.append(pending.pop(index))
                placed = True
                break
        if not placed:
            # Nothing fits: take the next one rather than dropping an activity.
            # A slightly worse ordering beats a shorter session.
            result.append(pending.pop(0))
    return result


def _may_follow(previous: Candidate | None, candidate: Candidate) -> bool:
    if previous is None:
        return True
    if previous.skill_id == candidate.skill_id:
        return False
    return not (previous.modality == "expressive" and candidate.modality == "expressive")


def violations(plan: Sequence[PlannedActivity], candidates: Sequence[Candidate]) -> list[str]:
    """Every constraint the plan breaks. Empty means the AI ordering may ship."""
    problems: list[str] = []
    if not plan:
        return ["plan is empty"]

    allowed = {c.skill_id for c in candidates}
    kinds = {c.skill_id: c.kind for c in candidates}
    mastered = {skill_id for skill_id, kind in kinds.items() if kind is CandidateKind.CONFIDENCE}

    # The bookend exception: a single mastered skill may appear at both ends.
    # Everything else must be unique, and the permutation check still runs over
    # the non-bookend body.
    body = list(plan)
    if len(plan) > 2 and plan[0].skill_id == plan[-1].skill_id and plan[0].skill_id in mastered:
        body = list(plan[:-1])
    try:
        enforce_permutation([p.skill_id for p in body], allowed)
    except GuardrailRejection as rejection:
        problems.append(f"not a permutation of the candidate set: {rejection.detail}")
    if mastered:
        if plan[0].skill_id not in mastered:
            problems.append("does not open on a mastered skill")
        if len(plan) > 1 and plan[-1].skill_id not in mastered:
            problems.append("does not close on a mastered skill")

    new_ids = {skill_id for skill_id, kind in kinds.items() if kind is CandidateKind.NEW}
    for position, activity in enumerate(plan, start=1):
        if activity.skill_id in new_ids and not (
            NEW_SKILL_MIN_POSITION <= position <= NEW_SKILL_MAX_POSITION
        ):
            problems.append(
                f"the new skill is at position {position}, not "
                f"{NEW_SKILL_MIN_POSITION}-{NEW_SKILL_MAX_POSITION}"
            )

    for previous, current in pairwise(plan):
        if previous.skill_id == current.skill_id:
            problems.append(f"same skill back to back: {current.skill_id}")
        if previous.modality == "expressive" and current.modality == "expressive":
            problems.append("two expressive activities in a row")

    return problems


def resolve_plan(
    *,
    ai_order: Sequence[str] | None,
    candidates: Sequence[Candidate],
) -> tuple[list[PlannedActivity], str, list[str]]:
    """The plan that ships, its source, and why the AI's was rejected if it was.

    Returns ('ai' | 'deterministic_fallback'). A rejection is invisible to the
    caregiver: the session runs either way, only the ordering differs.
    """
    fallback = deterministic_plan(candidates)
    if not ai_order:
        return fallback, "deterministic_fallback", ["no ai plan"]

    lookup = {c.skill_id: c for c in candidates}
    try:
        proposed = [
            PlannedActivity(
                skill_id=skill_id,
                modality=lookup[skill_id].modality,
                kind=lookup[skill_id].kind,
            )
            for skill_id in ai_order
        ]
    except KeyError as missing:
        return fallback, "deterministic_fallback", [f"unknown skill id {missing}"]

    problems = violations(proposed, candidates)
    if problems:
        return fallback, "deterministic_fallback", problems
    return proposed, "ai", []
