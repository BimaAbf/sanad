"""Spaced repetition — SM-2 derived, deliberately gentled.

Intervals grow more slowly than in an adult flashcard system because over-long
gaps in this population produce loss rather than consolidation. Transcribed from
docs/04c §C06.
"""

from __future__ import annotations

import datetime as dt
from bisect import bisect
from dataclasses import dataclass

#: Days. Capped at 35 — beyond that the gap stops consolidating and starts
#: costing the child the skill.
INTERVALS: tuple[int, ...] = (1, 2, 4, 7, 12, 21, 35)

EASE_MIN = 1.5
EASE_MAX = 2.6
EASE_DEFAULT = 2.3
EASE_PENALTY_ON_MISS = 0.2


@dataclass(frozen=True, slots=True)
class Schedule:
    interval_days: float
    ease_factor: float
    due_at: dt.datetime


def quality_from_latency(latency_ratio: float) -> int:
    """SM-2 response quality from how quickly the child answered.

    `latency_ratio` is the response time divided by the child's own configured
    wait time, so it is relative to that child rather than to a population
    norm — a child with a 15-second wait time is not penalised for taking
    12 seconds.
    """
    if latency_ratio < 0.6:
        return 5
    if latency_ratio < 1.0:
        return 4
    return 3


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def schedule(
    *,
    interval_days: float,
    ease_factor: float,
    correct: bool,
    latency_ratio: float,
    now: dt.datetime,
) -> Schedule:
    """The next review.

    A miss always resets to tomorrow rather than pushing the item further out.
    Forgetting is the signal to practise sooner, not later.
    """
    if not correct:
        return Schedule(
            interval_days=1,
            ease_factor=max(EASE_MIN, ease_factor - EASE_PENALTY_ON_MISS),
            due_at=now + dt.timedelta(days=1),
        )

    quality = quality_from_latency(latency_ratio)
    adjustment = 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)
    new_ease = clamp(ease_factor + adjustment, EASE_MIN, EASE_MAX)

    index = min(bisect(INTERVALS, interval_days), len(INTERVALS) - 1)
    next_interval = INTERVALS[index]
    days = next_interval * new_ease / EASE_DEFAULT
    return Schedule(
        interval_days=next_interval,
        ease_factor=new_ease,
        due_at=now + dt.timedelta(days=days),
    )


def days_overdue(due_at: dt.datetime, now: dt.datetime) -> float:
    return max(0.0, (now - due_at).total_seconds() / 86400.0)
