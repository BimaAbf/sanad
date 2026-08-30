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
window) was defeated by exactly that.

--------------------------------------------------------------------------------
2026-08-30 — THE SECOND DEFECT, AND THE REPLACEMENT
--------------------------------------------------------------------------------
The fix for that was a Hoeffding tail with the confidence divided across the
number of looks so far:

    margin(n, looks) = sqrt( ln(looks / alpha) / (2n) ),   window capped at 40

It stopped the random tapper. **It also stopped everybody else.** At twenty
flawless independent two-choice attempts it demands an observed accuracy of

    0.5 + sqrt( ln(20 / 1e-5) / (2 * 20) ) = 0.5 + 0.602 = 1.102

which no child can reach, because accuracy is bounded by 1. Worse, the 40-attempt
window puts a FLOOR under the margin — it can never fall below
sqrt(ln(looks/alpha)/80), which at 500 looks is 0.471 — so at two choices the
requirement stays above 0.97 forever and grows with the length of the run. A
child who answers correctly, independently, every single time, for months, is
never told they have mastered anything. That was measured and recorded as
REVIEW-QUEUE #5, and it makes half of the requirement false: random guessing
must not produce mastery, AND genuine repeated success must reach it.

The replacement is an **anytime-valid likelihood-ratio martingale** (Ville's
inequality) rather than a concentration bound. For each scored attempt i with
chance level p_i = 1/choice_count and outcome x_i, and for a fixed alternative
q > p_i, the per-attempt likelihood ratio is

    L_i(q) = q / p_i          if the answer was correct
             (1-q) / (1-p_i)  if it was not

and the running product over a MIXTURE of alternatives

    M_n = (1 / |Q|) * sum_{q in Q} prod_{i<=n} L_i(q)

is a non-negative martingale with E[M_n] = 1 under the null "this child is
guessing". Ville's inequality then gives, for the WHOLE run of any length:

    P( there exists n such that M_n >= 1/alpha )  <=  alpha

so the guard is simply `M_n >= 1/ALPHA`, with no union bound, no window, and no
multiplicity correction — the martingale is already valid at every stopping
time. Three properties this buys that the Hoeffding margin did not have:

  * it uses each attempt's OWN chance level, so a skill practised at two and at
    four choices is scored correctly rather than against an average;
  * evidence accumulates without bound, so perfect play converges. Twenty
    flawless independent attempts at two choices cross the line (nineteen do
    not); ten do at four choices, where the MIN_SCORED_ATTEMPTS floor then
    governs;
  * a child who struggled and then learned recovers, because the low-q members
    of the mixture pay only ln(0.4/0.5) per error rather than collapsing.

ALPHA is unchanged at 1e-5, so the safety property the random-tapper test
asserts is the same property, proved by a tighter argument.

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
#: evidence guard, across every evaluation in a run of any length. Ville's
#: inequality makes that a statement about the whole run, not about one look.
ACCURACY_ALPHA = 1e-5

#: The alternatives the mixture martingale is built from: "a child who knows
#: this skill answers correctly q of the time". Spread deliberately wide.
#: `bkt.P_SLIP = 0.25` says a knowing child is right about 0.75 of the time, so
#: 0.6-0.95 brackets that on both sides; the low members are what let a child
#: who improved recover from early errors, and the high members are what make
#: near-perfect play converge quickly.
ALTERNATIVES: tuple[float, ...] = (0.60, 0.70, 0.80, 0.90, 0.95)

#: Accuracy over a handful of attempts is noise. Below this many scored
#: attempts the rule withholds rather than guesses, whatever the martingale
#: says -- at four choices the evidence threshold is reachable in ten.
MIN_SCORED_ATTEMPTS = 12

#: The log of the martingale value the evidence must reach. Ville's inequality
#: bounds the probability of ever reaching it, under chance behaviour, at ALPHA.
EVIDENCE_LOG_THRESHOLD = math.log(1.0 / ACCURACY_ALPHA)


#: The share of everything this child has ever been asked about this skill,
#: unprompted, that must have been right.
#:
#: The martingale answers "is this child guessing?"; it does NOT answer "is this
#: child good enough at it to be told they have mastered it". Those are
#: different questions, and conflating them is how a child who is right 70% of
#: the time at two choices gets a mastery badge: 350 correct out of 500 is
#: overwhelming evidence of not-guessing (z ~ 8.9) and is also not mastery.
#:
#: Measured over the WHOLE scored history rather than a recent window, and that
#: choice is load-bearing. The rule is re-evaluated after every attempt, so a
#: 40-attempt window gives a 70%-accurate child roughly a one-in-nine chance
#: per look of a lucky 32/40 — which over a few hundred looks is a certainty.
#: A lifetime ratio cannot be won by waiting. The cost is that a child who
#: struggled early has to build the record back up: with ten early errors, a
#: perfect run reaches both this floor and the evidence threshold at the 57th
#: attempt rather than the 20th. That is a delay, not a block.
#:
#: 0.80 is an engineering choice standing in for a clinical one, like every
#: other constant here. → REVIEW-QUEUE.md #5
ACCURACY_FLOOR = 0.80

#: Retained only because `evaluate` still reports observed accuracy for the
#: clinician console, over a recent window rather than a lifetime average.
#: It no longer takes part in the decision.
ACCURACY_WINDOW = 40


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
    #: This skill's attempt history. The evidence martingale runs over ALL of
    #: it -- a caller that passes only a recent window is understating the
    #: evidence, not correcting for anything, because the anytime-valid
    #: construction already handles repeated evaluation.
    attempts: Sequence[AttemptRecord]
    #: Lifetime scored-attempt count. It drove the union bound of the Hoeffding
    #: margin that `evidence_log_ratio` replaced; the martingale needs no such
    #: correction, so this is now descriptive only. Kept because callers,
    #: fixtures and the clinician console all pass it.
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
    #: log of the mixture likelihood-ratio martingale over every scored attempt,
    #: and the line it has to cross. Surfaced so the clinician console and the
    #: AI inspector can show HOW MUCH evidence there is rather than only whether
    #: it was enough. Defaulted so existing constructions stay valid.
    evidence_log_ratio: float = 0.0
    evidence_threshold: float = EVIDENCE_LOG_THRESHOLD


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


def evidence_log_ratio(attempts: Sequence[AttemptRecord]) -> float:
    """log of the mixture likelihood-ratio martingale over the scored attempts.

    Computed in log space with a log-sum-exp, because the product itself
    overflows a float within a few hundred attempts and a mastery decision must
    not depend on how long a child has been using the product.

    `full_model` attempts are excluded upstream by `scored_attempts`: the child
    was shown the answer, so the response carries no information either way and
    including it would let the prompt ladder manufacture evidence.
    """
    scored = scored_attempts(attempts)
    if not scored:
        return 0.0

    # One running log-likelihood-ratio per alternative.
    totals = [0.0] * len(ALTERNATIVES)
    for attempt in scored:
        chance = 1.0 / max(attempt.choice_count, 2)
        for index, q in enumerate(ALTERNATIVES):
            if attempt.correct:
                totals[index] += math.log(q / chance)
            else:
                totals[index] += math.log((1.0 - q) / (1.0 - chance))

    highest = max(totals)
    pooled = highest + math.log(sum(math.exp(value - highest) for value in totals))
    # The mixture is uniform over ALTERNATIVES, so dividing by their count is
    # what keeps E[M_n] = 1 under the null and Ville's inequality applicable.
    return pooled - math.log(len(ALTERNATIVES))


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
    #
    # The martingale runs over the WHOLE scored history, not a window: it is a
    # statement about everything this child has done on this skill, and a
    # sliding window would reintroduce exactly the multiplicity the anytime-
    # valid construction exists to remove. The window survives only for the two
    # descriptive numbers the console renders.
    scored = scored_attempts(inputs.attempts)
    window = scored[-ACCURACY_WINDOW:]
    accuracy = observed_accuracy(window)
    chance = chance_level(window)
    evidence = evidence_log_ratio(inputs.attempts)

    if len(scored) < MIN_SCORED_ATTEMPTS:
        unmet.append("min_scored_attempts")
    if evidence < EVIDENCE_LOG_THRESHOLD:
        # Kept under its old name. It is the same condition -- "this is better
        # than chance, and not by luck" -- and it is referenced by name in
        # tests, in the clinician console and in REVIEW-QUEUE #5.
        unmet.append("accuracy_above_chance")
    if observed_accuracy(scored) < ACCURACY_FLOOR:
        unmet.append("accuracy_floor")

    return MasteryDecision(
        satisfied=not unmet,
        unmet=tuple(unmet),
        independent_ratio=ratio,
        accuracy=accuracy,
        chance_level=chance,
        evidence_log_ratio=evidence,
        evidence_threshold=EVIDENCE_LOG_THRESHOLD,
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
