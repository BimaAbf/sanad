"""THE SAFETY NET.

ORCHESTRATOR.md §4: the random-tapper test "is mechanical and it is the real
safety net." P07 requires it to run in CI.

    Simulate 500 attempts at each of 2, 3 and 4 choices with uniformly random
    selection; assert mastery_state never becomes `mastered` for any skill.

It also records, as an executable artefact, WHY the rule as specified in
docs/04c §C06 does not achieve this on its own. See mastery.py's module
docstring and docs/adr/009-bkt-parameters.md.
"""

from __future__ import annotations

import datetime as dt
import random
import statistics

import pytest

from app.modules.learning.domain.bkt import (
    P_L0,
    BktState,
    PromptLevel,
    bkt_update,
    guess_probability,
)
from app.modules.learning.domain.mastery import (
    ACCURACY_ALPHA,
    P_KNOWN_THRESHOLD,
    AttemptRecord,
    MasteryInputs,
    MasteryState,
    evaluate,
    mastery_rule,
    next_state,
)

START = dt.datetime(2026, 1, 1, 9, 0, tzinfo=dt.UTC)
ATTEMPTS = 500
CHOICE_COUNTS = (2, 3, 4)
SIMULATIONS = 60


def _simulate(
    *,
    choice_count: int,
    accuracy: float,
    rng: random.Random,
    attempts: int = ATTEMPTS,
    prompt_level: PromptLevel = PromptLevel.INDEPENDENT,
) -> tuple[BktState, list[AttemptRecord], MasteryState]:
    """Run a child through `attempts` activities, one every six hours.

    Six-hourly spacing means distinct_days and the 3-day delayed pass are both
    satisfied early. That is deliberate: it removes every incidental obstacle so
    the test measures the rule itself rather than the calendar.
    """
    state = BktState()
    records: list[AttemptRecord] = []
    mastery = MasteryState.NOT_STARTED
    first_correct: dt.datetime | None = None
    last_delayed: dt.datetime | None = None

    for index in range(attempts):
        at = START + dt.timedelta(hours=6 * index)
        correct = rng.random() < accuracy
        state = bkt_update(
            state, correct=correct, choice_count=choice_count, prompt_level=prompt_level
        )
        records.append(
            AttemptRecord(
                correct=correct, prompt_level=prompt_level, choice_count=choice_count, at=at
            )
        )
        if correct and first_correct is None:
            first_correct = at
        if correct and first_correct is not None and (at - first_correct).days >= 3:
            last_delayed = at

        distinct_days = len({r.at.date() for r in records})
        inputs = MasteryInputs(
            p_known=state.p_known,
            distinct_days=distinct_days,
            first_correct_at=first_correct,
            last_delayed_pass_at=last_delayed,
            # A rolling window: the rule judges recent behaviour, not a
            # lifetime average that a long history would dilute. The lifetime
            # count still drives the union bound over repeated looks.
            attempts=records[-40:],
            total_scored_attempts=len(records),
        )
        mastery = next_state(mastery, rule_satisfied=mastery_rule(inputs), p_known=state.p_known)
        if mastery is MasteryState.MASTERED:
            break

    return state, records, mastery


# ============================================================================
# THE REQUIRED ASSERTION
# ============================================================================


@pytest.mark.parametrize("choice_count", CHOICE_COUNTS)
def test_a_random_tapper_never_reaches_mastery(choice_count: int) -> None:
    """P07: 500 attempts of uniformly random tapping, at 2, 3 and 4 choices.

    `mastery_state` must never become `mastered`. Not rarely — never.
    """
    failures: list[int] = []
    for seed in range(SIMULATIONS):
        rng = random.Random(seed)
        _state, _records, mastery = _simulate(
            choice_count=choice_count,
            accuracy=1.0 / choice_count,  # pure chance, by construction
            rng=rng,
        )
        if mastery is MasteryState.MASTERED:
            failures.append(seed)

    assert not failures, (
        f"a random tapper reached mastery at {choice_count} choices "
        f"in {len(failures)}/{SIMULATIONS} simulations (seeds {failures[:5]}). "
        f"This is the safety net; it must never fail."
    )


@pytest.mark.parametrize("choice_count", CHOICE_COUNTS)
def test_a_random_tapper_never_even_satisfies_the_rule(choice_count: int) -> None:
    """Stronger: the rule itself is never satisfied, not merely the transition."""
    for seed in range(SIMULATIONS):
        rng = random.Random(seed)
        state = BktState()
        records: list[AttemptRecord] = []
        for index in range(ATTEMPTS):
            at = START + dt.timedelta(hours=6 * index)
            correct = rng.random() < 1.0 / choice_count
            state = bkt_update(
                state,
                correct=correct,
                choice_count=choice_count,
                prompt_level=PromptLevel.INDEPENDENT,
            )
            records.append(
                AttemptRecord(
                    correct=correct,
                    prompt_level=PromptLevel.INDEPENDENT,
                    choice_count=choice_count,
                    at=at,
                )
            )
            decision = evaluate(
                MasteryInputs(
                    p_known=state.p_known,
                    distinct_days=99,
                    first_correct_at=START,
                    last_delayed_pass_at=at,
                    attempts=records[-40:],
                    total_scored_attempts=len(records),
                )
            )
            assert not decision.satisfied, (
                f"rule satisfied at attempt {index}, seed {seed}, "
                f"choices {choice_count}: accuracy {decision.accuracy:.3f} "
                f"vs chance {decision.chance_level:.3f}"
            )


# ============================================================================
# WHY THE SPECIFIED RULE NEEDED AN ADDITION — executable evidence
# ============================================================================


@pytest.mark.parametrize("choice_count", CHOICE_COUNTS)
def test_p_known_alone_does_not_stop_a_random_tapper(choice_count: int) -> None:
    """The finding that forced the addition to the rule.

    docs/04c §C06's `p_known >= 0.90` term provides NO protection: the update
    ends with `p_known = posterior + (1 - posterior) * p_transit`, so every
    opportunity moves the estimate toward 1 whether the answer was right or
    wrong. Over hundreds of attempts it saturates for any behaviour at all.

    This test asserts the defect still exists, so that if someone later changes
    the BKT parameters and fixes it at the source, this test fails and points
    them at the now-redundant accuracy guard.
    """
    rng = random.Random(11)
    peaks = []
    for _ in range(30):
        state = BktState()
        peak = state.p_known
        for _ in range(ATTEMPTS):
            correct = rng.random() < 1.0 / choice_count
            state = bkt_update(
                state,
                correct=correct,
                choice_count=choice_count,
                prompt_level=PromptLevel.INDEPENDENT,
            )
            peak = max(peak, state.p_known)
        peaks.append(peak)

    assert statistics.median(peaks) >= P_KNOWN_THRESHOLD, (
        "p_known no longer saturates for a random tapper — the BKT model has "
        "changed. Re-examine whether mastery.ACCURACY_MARGIN_ABOVE_CHANCE is "
        "still needed, and update docs/adr/009-bkt-parameters.md."
    )


@pytest.mark.parametrize("choice_count", CHOICE_COUNTS)
def test_the_accuracy_guard_is_what_stops_the_tapper(choice_count: int) -> None:
    """Name the condition doing the work, so nobody removes it by accident."""
    rng = random.Random(3)
    _state, records, _mastery = _simulate(
        choice_count=choice_count, accuracy=1.0 / choice_count, rng=rng
    )
    decision = evaluate(
        MasteryInputs(
            p_known=0.99,
            distinct_days=99,
            first_correct_at=START,
            last_delayed_pass_at=START + dt.timedelta(days=10),
            attempts=records[-40:],
            total_scored_attempts=len(records),
        )
    )
    assert not decision.satisfied
    assert "accuracy_above_chance" in decision.unmet
    # And it is the ONLY unmet condition: everything the spec asks for passes.
    assert decision.unmet == ("accuracy_above_chance",)


# ============================================================================
# The complement: a child who is genuinely learning MUST reach mastery
# ============================================================================


@pytest.mark.parametrize("choice_count", CHOICE_COUNTS)
def test_a_consistently_correct_child_reaches_mastery_quickly(choice_count: int) -> None:
    """P07: bounded number of sessions for a tier-1 skill.

    A guard that blocks everything would pass the random-tapper test trivially.
    This is what stops that.
    """
    rng = random.Random(0)
    _state, records, mastery = _simulate(
        choice_count=choice_count, accuracy=1.0, rng=rng, attempts=200
    )
    assert mastery is MasteryState.MASTERED
    # docs/04c asks for "<= 6 sessions for a tier-1 skill". A skill being
    # introduced is practised roughly 5-8 times per session, so 6 sessions is
    # 30-48 attempts. The anytime-valid guard costs speed at 2 choices, where a
    # coin flip is already half right; see REVIEW-QUEUE.md #5.
    assert len(records) <= 48, f"took {len(records)} attempts to reach mastery"


@pytest.mark.parametrize(("choice_count", "accuracy"), [(3, 0.90), (4, 0.85)])
def test_a_mostly_correct_child_still_reaches_mastery(choice_count: int, accuracy: float) -> None:
    """Occasional slips must not block mastery — the realistic case.

    At 3 and 4 choices, where chance is 0.33 and 0.25, a child who is right most
    of the time clears the bar comfortably. At 2 choices they need to be nearly
    perfect, which is the cost of the guard and is recorded in REVIEW-QUEUE #5.
    """
    rng = random.Random(5)
    _state, _records, mastery = _simulate(
        choice_count=choice_count, accuracy=accuracy, rng=rng, attempts=300
    )
    assert mastery is MasteryState.MASTERED


def test_a_child_answering_only_at_full_model_never_reaches_mastery() -> None:
    """Being shown the answer every time is not learning it."""
    rng = random.Random(9)
    _state, _records, mastery = _simulate(
        choice_count=2,
        accuracy=1.0,
        rng=rng,
        prompt_level=PromptLevel.FULL_MODEL,
    )
    assert mastery is not MasteryState.MASTERED


def test_the_boundary_accuracy_that_separates_learning_from_guessing() -> None:
    """Where the line actually falls at 2 choices, stated in plain terms.

    The margin is not a constant — it tightens as a run lengthens. With a full
    40-attempt window early in a run it sits near 0.44, so a child must be
    around 94% accurate at 2 choices to be called mastered, and around 69% at
    4 choices where chance is only 0.25.

    That is demanding, and deliberately so: at 2 choices a coin flip is already
    50% right, so "better than chance" needs real separation before anyone tells
    a parent their child has mastered something.
    """
    from app.modules.learning.domain.mastery import accuracy_margin

    margin = accuracy_margin(window_size=40, total_looks=40)
    assert 0.40 < margin < 0.50, margin

    below = _simulate(choice_count=2, accuracy=0.70, rng=random.Random(21))[2]
    above = _simulate(choice_count=2, accuracy=1.0, rng=random.Random(21))[2]
    assert below is not MasteryState.MASTERED
    assert above is MasteryState.MASTERED
    assert ACCURACY_ALPHA == 1e-5


# ============================================================================
# BKT invariants
# ============================================================================


def test_p_known_stays_strictly_inside_zero_and_one_over_10000_sequences() -> None:
    """P07: p_known stays in (0,1) over 10,000 random attempt sequences.

    Random choice counts and random prompt levels, as specified.
    """
    rng = random.Random(1234)
    levels = list(PromptLevel)
    state = BktState()
    for index in range(10_000):
        if index % 50 == 0:
            state = BktState()
        state = bkt_update(
            state,
            correct=rng.random() < 0.5,
            choice_count=rng.choice([2, 3, 4]),
            prompt_level=rng.choice(levels),
        )
        assert 0.0 < state.p_known < 1.0, f"escaped at {index}: {state.p_known}"


def test_guess_probability_is_one_over_n_floored_at_two_choices() -> None:
    assert guess_probability(2) == 0.5
    assert guess_probability(4) == 0.25
    # A single choice would make a correct answer carry zero information.
    assert guess_probability(1) == 0.5
    assert guess_probability(0) == 0.5


def test_full_model_ignores_the_evidence_but_not_the_opportunity() -> None:
    """At full_model the posterior collapses to the prior; transit still applies."""
    state = BktState(p_known=0.5)
    wrong = bkt_update(state, correct=False, choice_count=2, prompt_level=PromptLevel.FULL_MODEL)
    right = bkt_update(state, correct=True, choice_count=2, prompt_level=PromptLevel.FULL_MODEL)
    assert wrong.p_known == pytest.approx(right.p_known), (
        "at full_model, right and wrong must be indistinguishable"
    )


def test_an_independent_correct_answer_moves_more_than_a_prompted_one() -> None:
    state = BktState(p_known=0.5)
    independent = bkt_update(
        state, correct=True, choice_count=2, prompt_level=PromptLevel.INDEPENDENT
    )
    gestural = bkt_update(state, correct=True, choice_count=2, prompt_level=PromptLevel.GESTURAL)
    partial = bkt_update(
        state, correct=True, choice_count=2, prompt_level=PromptLevel.PARTIAL_VERBAL
    )
    assert independent.p_known > gestural.p_known > partial.p_known


def test_more_choices_make_a_correct_answer_stronger_evidence() -> None:
    """Getting it right out of four is worth more than out of two."""
    state = BktState(p_known=0.5)
    two = bkt_update(state, correct=True, choice_count=2, prompt_level=PromptLevel.INDEPENDENT)
    four = bkt_update(state, correct=True, choice_count=4, prompt_level=PromptLevel.INDEPENDENT)
    assert four.p_known > two.p_known


def test_decay_never_falls_below_the_prior() -> None:
    from app.modules.learning.domain.bkt import apply_decay

    state = BktState(p_known=0.95)
    for days in (1, 7, 30, 365, 10_000):
        decayed = apply_decay(state, days_overdue=float(days), ease_factor=2.3)
        assert decayed >= P_L0 - 1e-9, f"decayed below the prior at {days} days"
        assert decayed <= 0.95


def test_decay_is_monotonic_in_time_and_a_no_op_when_not_overdue() -> None:
    from app.modules.learning.domain.bkt import apply_decay

    state = BktState(p_known=0.95)
    values = [apply_decay(state, days_overdue=float(d), ease_factor=2.3) for d in range(0, 60, 5)]
    assert values == sorted(values, reverse=True)
    assert apply_decay(state, days_overdue=0.0, ease_factor=2.3) == 0.95
    assert apply_decay(state, days_overdue=-5.0, ease_factor=2.3) == 0.95


def test_easier_skills_decay_more_slowly() -> None:
    from app.modules.learning.domain.bkt import apply_decay

    state = BktState(p_known=0.95)
    easy = apply_decay(state, days_overdue=30.0, ease_factor=2.6)
    hard = apply_decay(state, days_overdue=30.0, ease_factor=1.5)
    assert easy > hard
