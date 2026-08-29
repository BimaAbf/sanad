"""The engagement heuristic. NO AI — it must be instant.

Transcribed from docs/04c §C07. This runs between activities while a child is
waiting, so a model call here would put a network round trip in the middle of a
session. It is deterministic, pure, and takes microseconds.

The hard limits at the bottom override everything, including a `flowing` child:
there is no path where a session continues past a child who has disengaged.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

#: docs/04c §C07 hard limits.
MAX_SESSION_SECONDS = 10 * 60
MAX_ACTIVITIES = 15
MAX_CONSECUTIVE_NO_RESPONSE = 3

WINDOW = 5


class Affect(StrEnum):
    STRUGGLING = "struggling"
    TIRING = "tiring"
    FLOWING = "flowing"
    STEADY = "steady"


class EndReason(StrEnum):
    COMPLETED = "completed"
    FATIGUE = "fatigue"
    CAREGIVER_ENDED = "caregiver_ended"
    TIMEOUT = "timeout"
    DISCONNECT = "disconnect"


@dataclass(frozen=True, slots=True)
class AttemptSignal:
    """The subset of an attempt the heuristic reads."""

    result: str
    latency_ms: int
    prompt_level: str


@dataclass(frozen=True, slots=True)
class Signals:
    latency_drift: float
    error_run: int
    no_response: int
    prompt_climb: int


@dataclass(frozen=True, slots=True)
class AffectResponse:
    """What the session does next. Every field is a bounded, safe adjustment."""

    affect: Affect
    #: Insert a already-mastered skill right now.
    insert_confidence_item: bool = False
    #: Force the choice count down (never up beyond the child's own maximum).
    force_choice_count: int | None = None
    #: Start the prompt ladder one rung earlier.
    advance_prompt_ladder: bool = False
    #: Remaining activities allowed after this point.
    cap_remaining: int | None = None
    #: Multiplier on the child's configured wait time.
    wait_time_multiplier: float = 1.0
    #: Extra activities permitted beyond the plan.
    extra_activities: int = 0
    #: Drop the new skill if it has not been shown yet.
    skip_new_skill: bool = False
    allow_extra_choice_on_mastered: bool = False


def _trailing_run(attempts: Sequence[AttemptSignal], predicate: object) -> int:
    """Length of the trailing run satisfying `predicate`."""
    run = 0
    for attempt in reversed(attempts):
        if predicate(attempt):  # type: ignore[operator]
            run += 1
        else:
            break
    return run


def engagement(attempts: Sequence[AttemptSignal], baseline_ms: int) -> Signals:
    """Rolling signals over the last five attempts."""
    window = list(attempts[-WINDOW:])
    if not window:
        return Signals(latency_drift=1.0, error_run=0, no_response=0, prompt_climb=0)

    baseline = max(baseline_ms, 1)
    mean_latency = sum(a.latency_ms for a in window) / len(window)
    return Signals(
        latency_drift=mean_latency / baseline,
        error_run=_trailing_run(window, lambda a: a.result != "correct"),
        no_response=sum(1 for a in window if a.result == "no_response"),
        prompt_climb=sum(1 for a in window if a.prompt_level in ("partial_verbal", "full_model")),
    )


def classify(signals: Signals) -> Affect:
    """Order matters: struggling is checked before tiring, tiring before flowing."""
    if signals.no_response >= 2 or signals.error_run >= 3:
        return Affect.STRUGGLING
    if signals.latency_drift > 1.8 or signals.prompt_climb >= 3:
        return Affect.TIRING
    if signals.latency_drift < 0.7 and signals.error_run == 0:
        return Affect.FLOWING
    return Affect.STEADY


def respond(affect: Affect) -> AffectResponse:
    """The response table from docs/04c §C07."""
    match affect:
        case Affect.STRUGGLING:
            return AffectResponse(
                affect=affect,
                insert_confidence_item=True,
                force_choice_count=2,
                advance_prompt_ladder=True,
                cap_remaining=3,
            )
        case Affect.TIRING:
            return AffectResponse(
                affect=affect,
                cap_remaining=4,
                skip_new_skill=True,
                wait_time_multiplier=1.25,
            )
        case Affect.FLOWING:
            return AffectResponse(
                affect=affect,
                extra_activities=2,
                allow_extra_choice_on_mastered=True,
            )
        case _:
            return AffectResponse(affect=Affect.STEADY)


def assess(attempts: Sequence[AttemptSignal], baseline_ms: int) -> AffectResponse:
    return respond(classify(engagement(attempts, baseline_ms)))


def should_end(
    *,
    elapsed_seconds: float,
    activities_done: int,
    attempts: Sequence[AttemptSignal],
    planned: int,
    extra_allowed: int = 0,
    cap_remaining: int | None = None,
) -> EndReason | None:
    """Whether the session must end now, and why.

    The three hard limits override every affect response, including `flowing`.
    A child who has stopped responding is finished, whatever the plan said.
    """
    if _trailing_run(attempts, lambda a: a.result == "no_response") >= (
        MAX_CONSECUTIVE_NO_RESPONSE
    ):
        return EndReason.FATIGUE
    if elapsed_seconds >= MAX_SESSION_SECONDS:
        return EndReason.TIMEOUT
    if activities_done >= MAX_ACTIVITIES:
        return EndReason.COMPLETED
    if cap_remaining is not None and cap_remaining <= 0:
        return EndReason.FATIGUE
    if activities_done >= planned + extra_allowed:
        return EndReason.COMPLETED
    return None
