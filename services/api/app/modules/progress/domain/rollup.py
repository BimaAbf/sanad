"""Rollup computation. The same function serves both paths.

docs/04a §C09 asks for an incremental rollup on session end and a full nightly
rebuild that is "the correctness backstop for the incremental path". A backstop
is only a backstop if it can disagree — so the two paths must be able to produce
different answers in principle, and identical answers in fact.

The way to get that is to have exactly one function that computes a period's
numbers from a set of sessions, and to have the two paths differ only in *which
sessions they feed it*:

    incremental  →  every session in the affected periods, re-read
    nightly      →  every session ever, grouped into every period

Recomputing the whole period rather than adding a delta is what makes the
incremental path idempotent: replaying it is a no-op by construction, not by a
guard. A delta-based version would need an exactly-once guarantee that this
system does not have and should not need.

Pure. No I/O.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from app.modules.progress.domain.periods import ALL_TIME, day_key, local_date, week_key


@dataclass(frozen=True, slots=True)
class SessionFact:
    """One completed play session, flattened. The unit both paths aggregate."""

    session_id: str
    child_id: str
    started_at: dt.datetime
    minutes: int
    attempts: int
    correct: int
    #: category → attempts, for the by_category breakdown.
    by_category: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SkillStateFact:
    skill_id: str
    category: str
    state: str


@dataclass(frozen=True, slots=True)
class Rollup:
    child_id: str
    period: str
    sessions: int
    minutes: int
    attempts: int
    #: None rather than 0.0 when there were no attempts. A dashboard that reads
    #: 0% accuracy for a week with no play tells a parent their child failed
    #: everything, which is the opposite of what happened.
    accuracy: float | None
    skills_mastered: int
    skills_practising: int
    by_category: dict[str, int]

    def key(self) -> tuple[str, str]:
        return self.child_id, self.period


MASTERED_STATES = frozenset({"mastered", "retained"})
PRACTISING_STATES = frozenset({"practising", "emerging"})


def count_states(states: Sequence[SkillStateFact]) -> tuple[int, int]:
    mastered = sum(1 for state in states if state.state in MASTERED_STATES)
    practising = sum(1 for state in states if state.state in PRACTISING_STATES)
    return mastered, practising


def compute(
    *,
    child_id: str,
    period: str,
    sessions: Sequence[SessionFact],
    states: Sequence[SkillStateFact],
) -> Rollup:
    """One period's numbers. Deterministic in its inputs and nothing else."""
    attempts = sum(session.attempts for session in sessions)
    correct = sum(session.correct for session in sessions)
    by_category: dict[str, int] = {}
    for session in sessions:
        for category, count in session.by_category.items():
            by_category[category] = by_category.get(category, 0) + count

    mastered, practising = count_states(states)
    return Rollup(
        child_id=child_id,
        period=period,
        sessions=len(sessions),
        minutes=sum(session.minutes for session in sessions),
        attempts=attempts,
        accuracy=round(correct / attempts, 3) if attempts else None,
        skills_mastered=mastered,
        skills_practising=practising,
        by_category=dict(sorted(by_category.items())),
    )


def group_by_period(sessions: Iterable[SessionFact]) -> dict[str, list[SessionFact]]:
    """Every period each session belongs to → the sessions in it."""
    grouped: dict[str, list[SessionFact]] = {ALL_TIME: []}
    for session in sessions:
        date = local_date(session.started_at)
        for period in (day_key(date), week_key(date), ALL_TIME):
            grouped.setdefault(period, []).append(session)
    return grouped


def rebuild_all(
    *,
    child_id: str,
    sessions: Sequence[SessionFact],
    states: Sequence[SkillStateFact],
) -> list[Rollup]:
    """The nightly path: every period, from scratch."""
    grouped = group_by_period(sessions)
    return [
        compute(child_id=child_id, period=period, sessions=members, states=states)
        for period, members in sorted(grouped.items())
    ]


def rebuild_for_session(
    *,
    child_id: str,
    session: SessionFact,
    all_sessions: Sequence[SessionFact],
    states: Sequence[SkillStateFact],
) -> list[Rollup]:
    """The incremental path: only the periods this session touches.

    It still recomputes each of those periods in full from `all_sessions`, which
    is what makes replaying it a no-op.
    """
    date = local_date(session.started_at)
    affected = (day_key(date), week_key(date), ALL_TIME)
    grouped = group_by_period(all_sessions)
    return [
        compute(child_id=child_id, period=period, sessions=grouped.get(period, []), states=states)
        for period in affected
    ]


def diff(left: Sequence[Rollup], right: Sequence[Rollup]) -> list[str]:
    """Every disagreement between two rollup sets. Empty means identical.

    Used by the test that runs both paths over a 30-session history — and it is
    worth it being a real diff rather than an equality assertion, because when
    they do disagree the useful output is *which period and which field*.
    """
    by_key_left = {rollup.key(): rollup for rollup in left}
    by_key_right = {rollup.key(): rollup for rollup in right}

    problems: list[str] = []
    for key in sorted(set(by_key_left) | set(by_key_right)):
        a = by_key_left.get(key)
        b = by_key_right.get(key)
        if a is None or b is None:
            problems.append(f"{key[1]}: present in only one set")
            continue
        for field_name in (
            "sessions",
            "minutes",
            "attempts",
            "accuracy",
            "skills_mastered",
            "skills_practising",
            "by_category",
        ):
            if getattr(a, field_name) != getattr(b, field_name):
                problems.append(
                    f"{key[1]}.{field_name}: {getattr(a, field_name)} != {getattr(b, field_name)}"
                )
    return problems
