"""The per-skill counters a `skill_states` row carries. Pure, no I/O.

docs/02 six columns -- `total_attempts`, `total_correct`, `consecutive_correct`,
`avg_latency_ms`, `first_seen_at` and the distinct-day count -- are bookkeeping
rather than inference: they summarise what happened, and unlike `p_known` they
have exactly one right answer given the attempts.

They live here rather than in `service.py` for the reason every other
`domain/` module exists: this is the code the 100%-branch gate covers, and an
off-by-one in `consecutive_correct` is the kind of defect that reads as a
plausible number on a clinician's screen forever.

**`consecutive_correct` counts the TRAILING run, not the longest one.** The
column answers "is this child on a streak right now", which is what decides
whether the next activity steps up a difficulty tier. The longest-ever run is a
different fact and belongs to a different column, which docs/02 does not have.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AttemptFact:
    """One attempt, reduced to what the counters need."""

    correct: bool
    latency_ms: int | None
    at: dt.datetime


@dataclass(frozen=True, slots=True)
class StateSnapshot:
    total_attempts: int
    total_correct: int
    consecutive_correct: int
    #: None when no attempt carried a latency. A client that never sent one is
    #: not the same as a child who answered instantly, and storing 0 would make
    #: those indistinguishable in the only column that could tell them apart.
    avg_latency_ms: int | None
    first_seen_at: dt.datetime | None
    distinct_days: int


def trailing_correct(attempts: Sequence[AttemptFact]) -> int:
    """How many correct answers end the sequence."""
    run = 0
    for attempt in reversed(attempts):
        if not attempt.correct:
            break
        run += 1
    return run


def mean_latency(attempts: Sequence[AttemptFact]) -> int | None:
    """Mean of the attempts that reported one, rounded. None if none did."""
    latencies = [a.latency_ms for a in attempts if a.latency_ms is not None]
    if not latencies:
        return None
    return round(sum(latencies) / len(latencies))


def summarise(attempts: Sequence[AttemptFact]) -> StateSnapshot:
    """Every counter, from the full history.

    `attempts` must be in chronological order -- `first_seen_at` reads the head
    rather than scanning, and `consecutive_correct` reads the tail. The SQL that
    feeds this sorts on `(client_ts, id)`; nothing else calls it.
    """
    if not attempts:
        return StateSnapshot(
            total_attempts=0,
            total_correct=0,
            consecutive_correct=0,
            avg_latency_ms=None,
            first_seen_at=None,
            distinct_days=0,
        )

    return StateSnapshot(
        total_attempts=len(attempts),
        total_correct=sum(1 for a in attempts if a.correct),
        consecutive_correct=trailing_correct(attempts),
        avg_latency_ms=mean_latency(attempts),
        first_seen_at=attempts[0].at,
        distinct_days=len({a.at.date() for a in attempts}),
    )


#: `attempts.result` values that count as the child getting it right.
#: `accepted_on_effort` and `caregiver_confirmed` are successes by design
#: (docs/04d): the first is the voice tier accepting a genuine attempt at a hard
#: phoneme, the second is a caregiver overruling the recogniser. Treating either
#: as a failure would punish a child for the microphone.
CORRECT_RESULTS: frozenset[str] = frozenset(
    {"correct", "accepted_on_effort", "caregiver_confirmed"}
)


def is_correct(result: str) -> bool:
    return result in CORRECT_RESULTS


__all__ = [
    "CORRECT_RESULTS",
    "AttemptFact",
    "StateSnapshot",
    "is_correct",
    "mean_latency",
    "summarise",
    "trailing_correct",
]
