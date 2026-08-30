"""Bayesian Knowledge Tracing. Pure, no I/O, no AI.

Transcribed from docs/04c §C06. The parameter choices matter more than the
algorithm, and the reasoning is worth restating because it is a design position
rather than a tuning detail:

* `p_slip = 0.25` (literature default 0.10). Motor imprecision, attention
  variability and mis-taps are common in this population and are **not**
  evidence of not knowing. A low slip rate would punish children for their
  hands. This is the single most consequential constant in the file.
* `p_transit = 0.25` (default 0.10). Sessions are short and highly repetitive by
  design, so per-opportunity learning is higher than in a classroom study.
* `p_L0 = 0.15` (default 0.10). Colours and body parts are already familiar from
  home life.
* `p_guess = 1/n`, computed from the real choice count rather than assumed.

Every value is stored per skill-state row rather than as a global constant, so
they can be tuned per category and later fitted from real data by EM. See
docs/adr/009-bkt-parameters.md — **none of them is yet evidence-based.**
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

#: Defaults for a brand-new skill state (docs/02 §6 column defaults).
P_L0 = 0.15
P_TRANSIT = 0.25
P_SLIP = 0.25

#: p_known is clamped away from 0 and 1: a probability that reaches exactly 1
#: can never be revised downward by any amount of contrary evidence.
P_MIN = 0.001
P_MAX = 0.999


class PromptLevel(StrEnum):
    """The errorless-learning ladder. Mirrors the prompt_level enum."""

    INDEPENDENT = "independent"
    GESTURAL = "gestural"
    PARTIAL_VERBAL = "partial_verbal"
    FULL_MODEL = "full_model"


#: How much a response at each rung is allowed to move the estimate.
#:
#: `full_model` is 0.0: the answer was given to the child, so the response
#: carries no information about what they know. It is still *recorded*, because
#: the fact that they engaged at all matters, and because a session made
#: entirely of full models is a signal a caregiver needs to see.
PROMPT_DISCOUNT: dict[PromptLevel, float] = {
    PromptLevel.INDEPENDENT: 1.0,
    PromptLevel.GESTURAL: 0.6,
    PromptLevel.PARTIAL_VERBAL: 0.35,
    PromptLevel.FULL_MODEL: 0.0,
}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True, slots=True)
class BktState:
    p_known: float = P_L0
    p_transit: float = P_TRANSIT
    p_slip: float = P_SLIP
    #: Recorded per attempt from the real choice count; the stored value is the
    #: most recent one and exists mainly for inspection.
    p_guess: float = 0.5


def guess_probability(choice_count: int) -> float:
    """1/n, floored at two choices.

    A single-choice activity would give p_guess = 1.0, which makes a correct
    answer carry zero information — and the product never presents one.
    """
    return 1.0 / max(choice_count, 2)


def bkt_update(
    state: BktState,
    *,
    correct: bool,
    choice_count: int,
    prompt_level: PromptLevel,
    discount_override: float | None = None,
) -> BktState:
    """One Bayesian update plus the learning transition.

    `discount_override` replaces the ladder discount when a response does not
    come from the ladder at all — see the comment at the assignment.

    The prompt discount blends toward the posterior rather than replacing it, so
    a prompted response moves the estimate part of the way. At `full_model` the
    discount is zero and the posterior collapses back to the prior — the
    evidence is ignored, but the learning transition still applies, because
    being shown the answer is itself a learning opportunity.
    """
    p_guess = guess_probability(choice_count)
    # `discount_override` exists for one case the four-rung ladder cannot
    # express: docs/04d §3 weights a caregiver override at 0.5 of an
    # independent correct, and there is no rung at 0.5. Encoding it as
    # `gestural` (0.6) would overstate the evidence and `partial_verbal` (0.35)
    # would understate it, and both would make the number unfindable later.
    discount = (
        PROMPT_DISCOUNT[prompt_level]
        if discount_override is None
        else clamp(discount_override, 0.0, 1.0)
    )

    prior = state.p_known
    if correct:
        numerator = prior * (1 - state.p_slip)
        denominator = numerator + (1 - prior) * p_guess
    else:
        numerator = prior * state.p_slip
        denominator = numerator + (1 - prior) * (1 - p_guess)

    posterior = numerator / denominator if denominator > 0 else prior
    posterior = prior + (posterior - prior) * discount

    p_known = posterior + (1 - posterior) * state.p_transit
    return replace(state, p_known=clamp(p_known, P_MIN, P_MAX), p_guess=p_guess)


def apply_decay(state: BktState, *, days_overdue: float, ease_factor: float) -> float:
    """Forgetting. Returns the decayed p_known.

    Decays *toward the prior*, never below it: a child who has not practised in
    a month has not become less capable than a child who has never seen the
    skill at all.
    """
    if days_overdue <= 0:
        return state.p_known
    half_life = 14.0 * ease_factor / 2.3
    factor = 0.5 ** (days_overdue / half_life)
    decayed = P_L0 + (state.p_known - P_L0) * factor
    return clamp(decayed, P_MIN, P_MAX)
