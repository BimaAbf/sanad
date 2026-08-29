"""The deterministic mastery rule — the only way a skill becomes `mastered`.

The AI judge in C07 may return `withhold` and block a transition. It can never
cause one. That is principle P2, and the `ai_cannot_grant` CHECK constraint
enforces it in the database so even an application bug cannot bypass it.

================================================================================
A DEFECT IN THE SPECIFIED RULE, AND WHAT WAS DONE ABOUT IT
================================================================================
docs/04c §C06 states four conditions:

    p_known >= 0.90  AND  distinct_days >= 2  AND  a delayed pass >= 3 days
    after the first correct  AND  independent_ratio >= 0.60

P07's acceptance criteria require that a RANDOM TAPPER NEVER REACHES MASTERY, at
2, 3 or 4 choices, over 500 attempts. **The four conditions above do not achieve
that.** Measured directly (tests/unit/test_bkt_random_tapper.py):

    a uniformly random tapper reaches p_known ~= 0.999 in 500/500 simulations,
    at every choice count.

The cause is structural, not a tuning problem. The update ends with

    p_known = posterior + (1 - posterior) * p_transit

so every opportunity moves p_known toward 1 regardless of whether the answer was
right. Over hundreds of attempts it saturates for any behaviour whatsoever. The
other three conditions do not help: a random tapper answering unprompted has an
independent_ratio of 1.0, and given a few days will satisfy both the
distinct-days and delayed-pass conditions.

The accuracy guard below is therefore an ADDITION to the specified rule, not a
transcription of it. A random tapper's accuracy converges to 1/n by
construction, so requiring observed accuracy to clear chance is the one
condition random behaviour cannot satisfy at any length of run.

A FIXED margin is not enough, and getting this wrong once is instructive: the
rule is re-evaluated after every attempt, so over 500 attempts noise gets 500
chances to cross any fixed line. A first attempt at this (0.15 over a 40-attempt
window) was defeated by exactly that. The guard is therefore an ANYTIME-VALID
bound — a Hoeffding tail with the confidence level divided across the number of
evaluations so far, so the union bound over all looks still holds:

    margin(n, looks) = sqrt( ln(looks / alpha) / (2n) )

That gives a guarantee about the whole run rather than about one look:

    P(a child performing at chance ever satisfies this) <= ALPHA = 1e-5

**This addition has not been reviewed by anyone.** ALPHA, the window and the
minimum-attempt floor are engineering judgements, not clinical ones, and they
decide who is told their child has mastered a skill. They also make mastery
SLOWER to reach than docs/04c implies. → REVIEW-QUEUE.md #5
================================================================================
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.modules.learning.domain.bkt import PromptLevel

#: docs/04c §C06 thresholds.
P_KNOWN_THRESHOLD = 0.90
DISTINCT_DAYS_REQUIRED = 2
DELAYED_PASS_DAYS = 3
INDEPENDENT_RATIO_REQUIRED = 0.60

#: A correct independent response this long after mastery promotes to `retained`
#: — the state the dashboard celebrates, because it is the one that means
#: something.
RETAINED_AFTER_DAYS = 21

#: Below this p_known a mastered or retained skill lapses (docs/04c §C06 decay).
LAPSE_THRESHOLD = 0.70

# --- the addition, see the module docstring --------------------------------

#: Probability that a child performing at pure chance EVER satisfies the
#: accuracy guard, across every evaluation in a run of any length.
ACCURACY_ALPHA = 1e-5

#: Only the most recent attempts count, so a child who struggled early and then
#: learned is not held back by their own history forever.
ACCURACY_WINDOW = 40

#: Accuracy over a handful of attempts is noise. Below this many scored
#: attempts the rule withholds rather than guesses.
MIN_SCORED_ATTEMPTS = 12


class MasteryState(StrEnum):
    NOT_STARTED = "not_started"
    INTRODUCED = "introduced"
    PRACTISING = "practising"
    MASTERED = "mastered"
    RETAINED = "retained"
    LAPSED = "lapsed"


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    """The subset of an attempt the mastery rule needs. Pure data."""

    correct: bool
    prompt_level: PromptLevel
    choice_count: int
    at: dt.datetime


@dataclass(frozen=True, slots=True)
class MasteryInputs:
    p_known: float
    distinct_days: int
    first_correct_at: dt.datetime | None
    last_delayed_pass_at: dt.datetime | None
    #: Recent attempts. Only the last ACCURACY_WINDOW scored ones are used.
    attempts: Sequence[AttemptRecord]
    #: Lifetime scored-attempt count, which is the number of times this rule has
    #: been evaluated for this skill. Drives the union bound in
    #: `accuracy_margin`. Defaults to the length of `attempts` when a caller
    #: only has the window.
    total_scored_attempts: int = 0


@dataclass(frozen=True, slots=True)
class MasteryDecision:
    satisfied: bool
    #: Every condition that failed, so a clinician console can show *why* a
    #: skill has not been marked mastered rather than just that it has not.
    unmet: tuple[str, ...]
    independent_ratio: float
    accuracy: float
    chance_level: float


def independent_ratio(attempts: Sequence[AttemptRecord]) -> float:
    """Share of attempts answered without a prompt.

    An empty history is 0.0, not 1.0: no evidence is not the same as perfect
    evidence, and the difference decides whether a parent is told their child
    has mastered something.
    """
    if not attempts:
        return 0.0
    independent = sum(1 for a in attempts if a.prompt_level is PromptLevel.INDEPENDENT)
    return independent / len(attempts)


def scored_attempts(attempts: Sequence[AttemptRecord]) -> list[AttemptRecord]:
    """Attempts that carry information about knowledge.

    `full_model` is excluded: the child was shown the answer, so a correct
    response says nothing. Including them would let the prompt ladder inflate
    accuracy to 100%.
    """
    return [a for a in attempts if a.prompt_level is not PromptLevel.FULL_MODEL]


def observed_accuracy(attempts: Sequence[AttemptRecord]) -> float:
    scored = scored_attempts(attempts)
    if not scored:
        return 0.0
    return sum(1 for a in scored if a.correct) / len(scored)


def chance_level(attempts: Sequence[AttemptRecord]) -> float:
    """The accuracy pure guessing would produce, averaged over the real activities.

    Averaged rather than assumed, because a skill practised at 2 choices and at
    4 choices has a different chance floor in each.
    """
    scored = scored_attempts(attempts)
    if not scored:
        return 0.5
    return sum(1.0 / max(a.choice_count, 2) for a in scored) / len(scored)


def accuracy_margin(*, window_size: int, total_looks: int) -> float:
    """The margin above chance that observed accuracy must clear.

    A Hoeffding tail bound at confidence ALPHA / looks. Dividing the confidence
    across the number of evaluations is what makes this a statement about the
    whole run rather than about a single look — without it, repeated evaluation
    turns any fixed threshold into a coin flip that eventually comes up heads.

    The margin shrinks as the window fills and grows as the run lengthens, which
    is the right shape: more evidence per look earns a smaller margin, more looks
    demand a larger one.
    """
    if window_size <= 0:
        return 1.0
    looks = max(total_looks, 2)
    return math.sqrt(math.log(looks / ACCURACY_ALPHA) / (2 * window_size))


def evaluate(inputs: MasteryInputs) -> MasteryDecision:
    """Every condition, with the failures named."""
    unmet: list[str] = []

    if inputs.p_known < P_KNOWN_THRESHOLD:
        unmet.append("p_known")
    if inputs.distinct_days < DISTINCT_DAYS_REQUIRED:
        unmet.append("distinct_days")
    if inputs.last_delayed_pass_at is None:
        unmet.append("delayed_pass")

    ratio = independent_ratio(inputs.attempts)
    if ratio < INDEPENDENT_RATIO_REQUIRED:
        unmet.append("independent_ratio")

    # --- the addition ---
    scored = scored_attempts(inputs.attempts)
    window = scored[-ACCURACY_WINDOW:]
    accuracy = observed_accuracy(window)
    chance = chance_level(window)
    if len(scored) < MIN_SCORED_ATTEMPTS:
        unmet.append("min_scored_attempts")
    else:
        margin = accuracy_margin(
            window_size=len(window), total_looks=inputs.total_scored_attempts or len(scored)
        )
        if accuracy < chance + margin:
            unmet.append("accuracy_above_chance")

    return MasteryDecision(
        satisfied=not unmet,
        unmet=tuple(unmet),
        independent_ratio=ratio,
        accuracy=accuracy,
        chance_level=chance,
    )


def mastery_rule(inputs: MasteryInputs) -> bool:
    """The deterministic ground truth. `True` is the ONLY licence to promote."""
    return evaluate(inputs).satisfied


def is_delayed_pass(
    *, first_correct_at: dt.datetime | None, at: dt.datetime, correct: bool
) -> bool:
    """A correct response at least DELAYED_PASS_DAYS after the first correct one.

    This is what distinguishes learning from within-session repetition: getting
    it right five times in one sitting is not the same as getting it right again
    three days later.
    """
    if not correct or first_correct_at is None:
        return False
    return (at - first_correct_at) >= dt.timedelta(days=DELAYED_PASS_DAYS)


def next_state(
    current: MasteryState,
    *,
    rule_satisfied: bool,
    p_known: float,
    ai_withholds: bool = False,
    mastered_at: dt.datetime | None = None,
    now: dt.datetime | None = None,
) -> MasteryState:
    """The state transition.

    `ai_withholds` can only ever hold a child back from `mastered`; there is no
    path by which it advances one. Any change here must preserve that.
    """
    if current in (MasteryState.MASTERED, MasteryState.RETAINED):
        if p_known < LAPSE_THRESHOLD:
            return MasteryState.LAPSED
        if (
            current is MasteryState.MASTERED
            and mastered_at is not None
            and now is not None
            and (now - mastered_at) >= dt.timedelta(days=RETAINED_AFTER_DAYS)
            and rule_satisfied
        ):
            return MasteryState.RETAINED
        return current

    if rule_satisfied and not ai_withholds:
        return MasteryState.MASTERED

    if current is MasteryState.NOT_STARTED:
        return MasteryState.INTRODUCED
    if current is MasteryState.INTRODUCED:
        return MasteryState.PRACTISING
    return current
