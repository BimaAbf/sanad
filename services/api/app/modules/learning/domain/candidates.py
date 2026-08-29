"""Candidate generation for a play session. Pure, deterministic, no AI.

The composition rule from docs/04c §C06 is a clinical position, not a product
preference: **at most one new skill per session**, and **none at all** while
three or more skills are still `practising`. Introducing two competing new items
in one eight-minute session is how you produce interference and frustration in
this population.

The AI planner in C07 may reorder what this returns. It may never add to it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.modules.learning.domain.mastery import MasteryState

DEFAULT_LIMIT = 8
MAX_DUE = 5
MAX_LAPSED = 2
MAX_NEW = 1
MAX_CONFIDENCE = 1

#: No new skill is introduced while at least this many are mid-flight.
PRACTISING_BLOCKS_NEW = 3


class CandidateKind(StrEnum):
    LAPSED = "lapsed"
    DUE = "due"
    NEW = "new"
    CONFIDENCE = "confidence"


@dataclass(frozen=True, slots=True)
class SkillSnapshot:
    """What candidate selection needs to know about one skill for one child."""

    skill_id: str
    modality: str
    state: MasteryState
    due_at: dt.datetime | None
    intro_order: int
    difficulty_tier: int
    #: Skill ids that must be mastered or retained before this one is eligible.
    prerequisites: tuple[str, ...] = ()
    #: Seeded from the PGEE assessment's linked_skills: skills the assessment
    #: identified as the child's next step come first among equals.
    pgee_linked: bool = False


@dataclass(frozen=True, slots=True)
class Candidate:
    skill_id: str
    modality: str
    kind: CandidateKind
    priority: int


def _satisfied(snapshot: SkillSnapshot, mastered: frozenset[str]) -> bool:
    return all(prerequisite in mastered for prerequisite in snapshot.prerequisites)


def candidates(
    snapshots: Sequence[SkillSnapshot],
    *,
    now: dt.datetime,
    limit: int = DEFAULT_LIMIT,
) -> list[Candidate]:
    """The session plan, in order.

    Order of business:
      1. `lapsed` first — re-entering the review queue at high priority is the
         whole point of the lapse state.
      2. due reviews.
      3. at most one new skill, and only if fewer than three are practising.
      4. one already-mastered skill last, so the session always ends on a win.
    """
    mastered = frozenset(
        s.skill_id for s in snapshots if s.state in (MasteryState.MASTERED, MasteryState.RETAINED)
    )
    practising = sum(1 for s in snapshots if s.state is MasteryState.PRACTISING)

    lapsed = sorted(
        (s for s in snapshots if s.state is MasteryState.LAPSED),
        key=lambda s: (s.difficulty_tier, s.intro_order),
    )[:MAX_LAPSED]

    due = sorted(
        (
            s
            for s in snapshots
            if s.state in (MasteryState.INTRODUCED, MasteryState.PRACTISING)
            and s.due_at is not None
            and s.due_at <= now
        ),
        key=lambda s: (s.due_at or now, s.intro_order),
    )[:MAX_DUE]

    new: list[SkillSnapshot] = []
    if practising < PRACTISING_BLOCKS_NEW:
        eligible = sorted(
            (
                s
                for s in snapshots
                if s.state is MasteryState.NOT_STARTED and _satisfied(s, mastered)
            ),
            # A skill the assessment pointed at outranks intro order.
            key=lambda s: (not s.pgee_linked, s.intro_order),
        )
        new = eligible[:MAX_NEW]

    confidence = sorted(
        (s for s in snapshots if s.state in (MasteryState.MASTERED, MasteryState.RETAINED)),
        key=lambda s: (s.difficulty_tier, s.intro_order),
    )[:MAX_CONFIDENCE]

    ordered: list[Candidate] = []
    seen: set[tuple[str, str]] = set()

    def add(items: Sequence[SkillSnapshot], kind: CandidateKind) -> None:
        for priority, snapshot in enumerate(items):
            key = (snapshot.skill_id, snapshot.modality)
            if key in seen:
                continue
            seen.add(key)
            ordered.append(
                Candidate(
                    skill_id=snapshot.skill_id,
                    modality=snapshot.modality,
                    kind=kind,
                    priority=priority,
                )
            )

    add(lapsed, CandidateKind.LAPSED)
    add(due, CandidateKind.DUE)
    add(new, CandidateKind.NEW)
    add(confidence, CandidateKind.CONFIDENCE)

    return ordered[:limit]


def count_new(selected: Sequence[Candidate]) -> int:
    return sum(1 for c in selected if c.kind is CandidateKind.NEW)
