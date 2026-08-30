"""The mastery regression matrix.

One test per behaviour the final specification names, run through the same
`BktState` → `MasteryInputs` → `evaluate` → `next_state` path the product runs,
so every row here is a statement about what a real child would experience.

The two properties the whole file exists to hold in place, together:

  A. random guessing cannot easily produce mastery — at any length of run, at
     any choice count, ever;
  B. genuine repeated independent success DOES reach mastery, after a bounded
     and stateable amount of evidence.

Before 2026-08-30 the rule satisfied (A) and violated (B): the Hoeffding margin
demanded accuracy 1.102 at twenty flawless two-choice attempts. `mastery.py`'s
module docstring has the derivation; this file has the consequences.

Nothing here is clinically validated. The thresholds are engineering choices.
→ REVIEW-QUEUE.md #5
"""

from __future__ import annotations

import datetime as dt
import random

import pytest

from app.modules.learning.domain.bkt import (
    BktState,
    PromptLevel,
    apply_decay,
    bkt_update,
)
from app.modules.learning.domain.candidates import (
    CandidateKind,
    SkillSnapshot,
    candidates,
)
from app.modules.learning.domain.mastery import (
    ACCURACY_FLOOR,
    EVIDENCE_LOG_THRESHOLD,
    LAPSE_THRESHOLD,
    MIN_SCORED_ATTEMPTS,
    AttemptRecord,
    MasteryInputs,
    MasteryState,
    evaluate,
    evidence_log_ratio,
    mastery_rule,
    next_state,
)

START = dt.datetime(2026, 1, 1, 9, 0, tzinfo=dt.UTC)


def _run(
    outcomes: list[bool],
    *,
    choice_count: int = 2,
    prompt_level: PromptLevel = PromptLevel.INDEPENDENT,
    hours_between: int = 6,
) -> tuple[MasteryState, BktState, list[AttemptRecord], int]:
    """Play `outcomes` through the real update path.

    Returns the final state, the BKT state, the records, and the 1-indexed
    attempt at which `mastered` was first reached (0 if never).

    Six-hourly spacing so `distinct_days` and the three-day delayed pass are
    satisfied early: this file measures the evidence conditions, and a calendar
    obstacle would mask them.
    """
    bkt = BktState()
    records: list[AttemptRecord] = []
    state = MasteryState.NOT_STARTED
    first_correct: dt.datetime | None = None
    last_delayed: dt.datetime | None = None
    mastered_at = 0

    for index, correct in enumerate(outcomes):
        at = START + dt.timedelta(hours=hours_between * index)
        bkt = bkt_update(bkt, correct=correct, choice_count=choice_count, prompt_level=prompt_level)
        records.append(
            AttemptRecord(
                correct=correct, prompt_level=prompt_level, choice_count=choice_count, at=at
            )
        )
        if correct:
            if first_correct is None:
                first_correct = at
            elif (at - first_correct).days >= 3:
                last_delayed = at

        satisfied = mastery_rule(
            MasteryInputs(
                p_known=bkt.p_known,
                distinct_days=len({r.at.date() for r in records}),
                first_correct_at=first_correct,
                last_delayed_pass_at=last_delayed,
                attempts=records,
                total_scored_attempts=len(records),
            )
        )
        state = next_state(state, rule_satisfied=satisfied, p_known=bkt.p_known)
        if state is MasteryState.MASTERED and mastered_at == 0:
            mastered_at = index + 1

    return state, bkt, records, mastered_at


# ===========================================================================
# B — genuine success reaches mastery
# ===========================================================================


@pytest.mark.parametrize(
    ("choice_count", "expected_attempts"),
    [(2, 20), (3, 13), (4, 13)],
)
def test_perfect_independent_performance_reaches_mastery(
    choice_count: int, expected_attempts: int
) -> None:
    """The exact attempt at which flawless independent play crosses.

    Stated as an equality rather than a bound because it is the number that was
    infinite before, and a regression that pushes it out is the exact defect
    this file exists to prevent. At four choices the martingale is satisfied at
    ten and `MIN_SCORED_ATTEMPTS` = 12 at twelve, so what governs there is the
    calendar: the three-day delayed pass is earned on the thirteenth attempt at
    this helper's six-hourly spacing. At three choices both bind at thirteen.
    """
    state, _bkt, _records, at = _run([True] * 60, choice_count=choice_count)
    assert state is MasteryState.MASTERED
    assert at == expected_attempts, f"reached mastery at attempt {at}"


def test_a_child_who_is_right_nine_times_in_ten_reaches_mastery() -> None:
    """The realistic strong learner: occasional slips must not block mastery."""
    outcomes = [(index % 10) != 0 for index in range(120)]
    state, _bkt, _records, at = _run(outcomes)
    assert state is MasteryState.MASTERED
    assert 0 < at <= 60, f"took {at} attempts"


def test_repeated_success_across_many_sessions_reaches_mastery() -> None:
    """Six sessions, six attempts each, one session a day, all correct.

    The shape docs/04c describes for a tier-1 skill, run as a calendar rather
    than as a stream — so `distinct_days` and the delayed pass are earned the
    way a family would earn them, not manufactured by the helper's spacing.
    """
    bkt = BktState()
    records: list[AttemptRecord] = []
    state = MasteryState.NOT_STARTED
    first_correct: dt.datetime | None = None
    last_delayed: dt.datetime | None = None

    for day in range(6):
        for slot in range(6):
            at = START + dt.timedelta(days=day, minutes=slot * 2)
            bkt = bkt_update(
                bkt, correct=True, choice_count=2, prompt_level=PromptLevel.INDEPENDENT
            )
            records.append(
                AttemptRecord(
                    correct=True,
                    prompt_level=PromptLevel.INDEPENDENT,
                    choice_count=2,
                    at=at,
                )
            )
            if first_correct is None:
                first_correct = at
            elif (at - first_correct).days >= 3:
                last_delayed = at
            state = next_state(
                state,
                rule_satisfied=mastery_rule(
                    MasteryInputs(
                        p_known=bkt.p_known,
                        distinct_days=len({r.at.date() for r in records}),
                        first_correct_at=first_correct,
                        last_delayed_pass_at=last_delayed,
                        attempts=records,
                        total_scored_attempts=len(records),
                    )
                ),
                p_known=bkt.p_known,
            )

    assert state is MasteryState.MASTERED


def test_rapid_improvement_reaches_mastery_sooner_than_gradual_improvement() -> None:
    """Two children, the same number of errors, arranged differently."""
    rapid = [False] * 6 + [True] * 80
    gradual = [(index % 12) >= 6 for index in range(24)] + [True] * 62

    _s1, _b1, _r1, rapid_at = _run(rapid)
    _s2, _b2, _r2, gradual_at = _run(gradual)

    assert rapid_at > 0 and gradual_at > 0
    assert rapid_at < gradual_at


def test_a_child_who_struggled_and_then_learned_still_gets_there() -> None:
    """Ten errors do not become a life sentence.

    The evidence martingale and the lifetime accuracy floor both have to be
    rebuilt, which takes 57 attempts rather than 20 — a delay, not a block, and
    the number is asserted so that "recovers eventually" cannot quietly become
    "recovers after four hundred attempts".
    """
    state, _bkt, _records, at = _run([False] * 10 + [True] * 120)
    assert state is MasteryState.MASTERED
    assert at == 57, f"recovered at attempt {at}"


# ===========================================================================
# A — guessing, and everything that is not evidence
# ===========================================================================


@pytest.mark.parametrize("choice_count", [2, 3, 4])
def test_random_guessing_never_reaches_mastery(choice_count: int) -> None:
    """500 attempts, 40 seeds, at every choice count. The safety net."""
    for seed in range(40):
        rng = random.Random(seed)
        outcomes = [rng.random() < 1.0 / choice_count for _ in range(500)]
        state, _bkt, _records, _at = _run(outcomes, choice_count=choice_count)
        assert state is not MasteryState.MASTERED, f"seed {seed}, {choice_count} choices"


def test_fifty_fifty_performance_at_two_choices_is_never_mastery() -> None:
    """Exactly chance, arranged with no randomness at all to remove luck."""
    state, _bkt, records, _at = _run([index % 2 == 0 for index in range(400)])
    assert state is not MasteryState.MASTERED
    assert evidence_log_ratio(records) < EVIDENCE_LOG_THRESHOLD


def test_seventy_percent_at_two_choices_is_evidence_but_not_mastery() -> None:
    """The two conditions are separate, and this is why.

    350 correct out of 500 at two choices is overwhelming evidence that the
    child is not guessing — and it is not mastery. The martingale clears; the
    lifetime accuracy floor does not.
    """
    outcomes = [(index % 10) < 7 for index in range(500)]
    state, _bkt, records, _at = _run(outcomes)
    assert evidence_log_ratio(records) >= EVIDENCE_LOG_THRESHOLD
    decision = evaluate(
        MasteryInputs(
            p_known=0.99,
            distinct_days=99,
            first_correct_at=START,
            last_delayed_pass_at=START + dt.timedelta(days=9),
            attempts=records,
            total_scored_attempts=len(records),
        )
    )
    assert decision.unmet == ("accuracy_floor",)
    assert state is not MasteryState.MASTERED


def test_alternating_performance_never_settles_into_mastery() -> None:
    """Right, wrong, right, wrong — 50% dressed up as consistency."""
    state, _bkt, _records, _at = _run([index % 2 == 0 for index in range(300)])
    assert state is not MasteryState.MASTERED


def test_repeated_incorrect_answers_reach_practising_and_stop() -> None:
    """A child getting it wrong every time still progresses through the ladder.

    `introduced` then `practising` — because they are being taught, and neither
    state is a judgement — and no further. There is no state below `practising`
    to fall to and inventing one would put a word on a caregiver's screen that
    docs/02's enum does not have.
    """
    state, bkt, _records, at = _run([False] * 100)
    assert at == 0
    assert state is MasteryState.PRACTISING
    assert bkt.p_known < 0.9


def test_a_full_demonstration_never_proves_independent_mastery() -> None:
    """Being shown the answer a hundred times is not knowing it.

    The strongest form of the claim: perfect performance, forever, at
    `full_model`. The evidence martingale is exactly 1 (log 0) because those
    attempts carry no information, and mastery is never reached.
    """
    state, _bkt, records, at = _run([True] * 200, prompt_level=PromptLevel.FULL_MODEL)
    assert at == 0
    assert state is not MasteryState.MASTERED
    assert evidence_log_ratio(records) == 0.0


def test_supported_answers_are_weaker_evidence_than_independent_ones() -> None:
    """The prompt ladder discounts, and the discount is ordered.

    Both halves: a supported run moves `p_known` less than an independent one,
    and a run answered entirely at `gestural` fails the independent-ratio
    condition however accurate it is.
    """
    # Eight attempts, not forty: `p_known` is clamped at P_MAX = 0.999 and both
    # ladders reach it eventually, so a long run compares two saturated numbers
    # and proves nothing. The discount is visible while there is headroom.
    _s1, independent, _r1, _at1 = _run([True] * 8)
    _s2, gestural, _r2, _at2 = _run([True] * 8, prompt_level=PromptLevel.GESTURAL)
    assert independent.p_known > gestural.p_known

    _s3, _b3, records, gestural_at = _run([True] * 40, prompt_level=PromptLevel.GESTURAL)
    _s4, _b4, _r4, independent_at = _run([True] * 40)
    assert independent_at > 0
    assert gestural_at == 0

    decision = evaluate(
        MasteryInputs(
            p_known=0.99,
            distinct_days=9,
            first_correct_at=START,
            last_delayed_pass_at=START + dt.timedelta(days=9),
            attempts=records,
            total_scored_attempts=len(records),
        )
    )
    assert "independent_ratio" in decision.unmet


# ===========================================================================
# Regression, decay and lapse
# ===========================================================================


def test_a_mastered_skill_lapses_when_the_estimate_decays_past_the_threshold() -> None:
    state, bkt, _records, at = _run([True] * 40)
    assert at > 0 and state is MasteryState.MASTERED

    decayed = apply_decay(bkt, days_overdue=120.0, ease_factor=2.3)
    assert decayed < LAPSE_THRESHOLD
    assert next_state(state, rule_satisfied=False, p_known=decayed) is MasteryState.LAPSED


def test_decay_never_takes_a_child_below_a_child_who_never_started() -> None:
    from app.modules.learning.domain.bkt import P_L0

    bkt = BktState(p_known=0.97)
    for days in (1.0, 30.0, 365.0, 100_000.0):
        assert apply_decay(bkt, days_overdue=days, ease_factor=2.3) >= P_L0 - 1e-9


def test_a_lapsed_skill_is_the_first_thing_the_next_session_offers() -> None:
    """Regression is not merely recorded; it changes what the child is given."""
    now = START + dt.timedelta(days=40)
    plan = candidates(
        [
            SkillSnapshot(
                skill_id="colour_blue",
                modality="receptive",
                state=MasteryState.LAPSED,
                due_at=now - dt.timedelta(days=5),
                intro_order=9,
                difficulty_tier=1,
            ),
            SkillSnapshot(
                skill_id="colour_red",
                modality="receptive",
                state=MasteryState.PRACTISING,
                due_at=now - dt.timedelta(days=1),
                intro_order=1,
                difficulty_tier=1,
            ),
        ],
        now=now,
    )
    assert plan[0].skill_id == "colour_blue"
    assert plan[0].kind is CandidateKind.LAPSED


def test_a_regression_after_mastery_moves_the_estimate_down() -> None:
    """Ten wrong answers after mastery must be visible in the estimate."""
    _state, bkt, _records, _at = _run([True] * 40)
    before = bkt.p_known
    for _ in range(10):
        bkt = bkt_update(bkt, correct=False, choice_count=2, prompt_level=PromptLevel.INDEPENDENT)
    assert bkt.p_known < before


# ===========================================================================
# Prerequisites
# ===========================================================================


def test_a_skill_whose_prerequisite_is_unmet_is_never_offered() -> None:
    now = START
    snapshots = [
        SkillSnapshot(
            skill_id="count_to_five",
            modality="receptive",
            state=MasteryState.NOT_STARTED,
            due_at=None,
            intro_order=2,
            difficulty_tier=2,
            prerequisites=("count_to_three",),
        ),
    ]
    assert candidates(snapshots, now=now) == []


def test_the_same_skill_is_offered_once_its_prerequisite_is_mastered() -> None:
    now = START
    snapshots = [
        SkillSnapshot(
            skill_id="count_to_three",
            modality="receptive",
            state=MasteryState.MASTERED,
            due_at=None,
            intro_order=1,
            difficulty_tier=1,
        ),
        SkillSnapshot(
            skill_id="count_to_five",
            modality="receptive",
            state=MasteryState.NOT_STARTED,
            due_at=None,
            intro_order=2,
            difficulty_tier=2,
            prerequisites=("count_to_three",),
        ),
    ]
    offered = {candidate.skill_id for candidate in candidates(snapshots, now=now)}
    assert "count_to_five" in offered


def test_a_retained_prerequisite_also_unlocks_the_next_skill() -> None:
    """`retained` is stronger than `mastered`, not a different branch."""
    snapshots = [
        SkillSnapshot(
            skill_id="count_to_three",
            modality="receptive",
            state=MasteryState.RETAINED,
            due_at=None,
            intro_order=1,
            difficulty_tier=1,
        ),
        SkillSnapshot(
            skill_id="count_to_five",
            modality="receptive",
            state=MasteryState.NOT_STARTED,
            due_at=None,
            intro_order=2,
            difficulty_tier=2,
            prerequisites=("count_to_three",),
        ),
    ]
    offered = {c.skill_id for c in candidates(snapshots, now=START)}
    assert "count_to_five" in offered


# ===========================================================================
# Boundary conditions
# ===========================================================================


def test_the_evidence_threshold_is_a_boundary_not_a_range() -> None:
    """One attempt either side of the line, at every choice count."""
    for choice_count, crossing in ((2, 20), (3, 13), (4, 10)):
        below = [
            AttemptRecord(
                correct=True,
                prompt_level=PromptLevel.INDEPENDENT,
                choice_count=choice_count,
                at=START,
            )
            for _ in range(crossing - 1)
        ]
        at_line = [*below, below[0]]
        assert evidence_log_ratio(below) < EVIDENCE_LOG_THRESHOLD
        assert evidence_log_ratio(at_line) >= EVIDENCE_LOG_THRESHOLD


def test_the_accuracy_floor_is_inclusive() -> None:
    """Exactly 80% passes the floor; one error more does not."""
    exactly = [(index % 5) != 0 for index in range(40)]
    just_under = [*exactly[:-1], False]

    def unmet(outcomes: list[bool]) -> tuple[str, ...]:
        records = [
            AttemptRecord(
                correct=correct,
                prompt_level=PromptLevel.INDEPENDENT,
                choice_count=4,
                at=START + dt.timedelta(hours=6 * index),
            )
            for index, correct in enumerate(outcomes)
        ]
        return evaluate(
            MasteryInputs(
                p_known=0.99,
                distinct_days=99,
                first_correct_at=START,
                last_delayed_pass_at=START + dt.timedelta(days=9),
                attempts=records,
                total_scored_attempts=len(records),
            )
        ).unmet

    assert sum(exactly) / len(exactly) == pytest.approx(ACCURACY_FLOOR)
    assert "accuracy_floor" not in unmet(exactly)
    assert "accuracy_floor" in unmet(just_under)


def test_below_the_minimum_scored_attempts_the_rule_withholds() -> None:
    """Even perfect play at four choices, where the martingale is satisfied."""
    records = [
        AttemptRecord(
            correct=True,
            prompt_level=PromptLevel.INDEPENDENT,
            choice_count=4,
            at=START + dt.timedelta(hours=6 * index),
        )
        for index in range(MIN_SCORED_ATTEMPTS - 1)
    ]
    assert evidence_log_ratio(records) >= EVIDENCE_LOG_THRESHOLD
    decision = evaluate(
        MasteryInputs(
            p_known=0.99,
            distinct_days=99,
            first_correct_at=START,
            last_delayed_pass_at=START + dt.timedelta(days=9),
            attempts=records,
            total_scored_attempts=len(records),
        )
    )
    assert decision.unmet == ("min_scored_attempts",)


def test_an_empty_history_satisfies_nothing_and_says_so() -> None:
    decision = evaluate(
        MasteryInputs(
            p_known=0.99,
            distinct_days=99,
            first_correct_at=START,
            last_delayed_pass_at=START,
            attempts=[],
        )
    )
    assert not decision.satisfied
    assert set(decision.unmet) >= {
        "independent_ratio",
        "min_scored_attempts",
        "accuracy_above_chance",
        "accuracy_floor",
    }


def test_the_evidence_ratio_survives_a_run_long_enough_to_overflow_a_product() -> None:
    """The martingale is computed in log space, and this is why.

    2000 correct answers at four choices is a likelihood ratio around 10^1100,
    which is not a float. A mastery decision must not depend on how long a
    child has been using the product.
    """
    records = [
        AttemptRecord(
            correct=True,
            prompt_level=PromptLevel.INDEPENDENT,
            choice_count=4,
            at=START + dt.timedelta(hours=6 * index),
        )
        for index in range(2000)
    ]
    value = evidence_log_ratio(records)
    assert value > EVIDENCE_LOG_THRESHOLD
    assert value == value  # not NaN
    assert value < float("inf")


def test_an_ai_verdict_can_only_ever_withhold_mastery() -> None:
    """Structural, and asserted so a future edit to `next_state` cannot lose it."""
    for current in MasteryState:
        withheld = next_state(current, rule_satisfied=True, p_known=0.99, ai_withholds=True)
        granted = next_state(current, rule_satisfied=True, p_known=0.99, ai_withholds=False)
        assert withheld is not MasteryState.MASTERED or current in (
            MasteryState.MASTERED,
            MasteryState.RETAINED,
        )
        # And the AI never makes anything happen that would not have happened.
        assert granted in (MasteryState.MASTERED, MasteryState.RETAINED, current) or (
            granted is not withheld
        )

    # The AI cannot promote a child the rule refuses, either.
    assert (
        next_state(MasteryState.PRACTISING, rule_satisfied=False, p_known=0.99, ai_withholds=False)
        is MasteryState.PRACTISING
    )
