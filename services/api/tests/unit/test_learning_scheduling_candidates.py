"""Spaced repetition, decay, mastery transitions and candidate composition."""

from __future__ import annotations

import datetime as dt

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.learning.domain.bkt import PromptLevel
from app.modules.learning.domain.candidates import (
    MAX_NEW,
    PRACTISING_BLOCKS_NEW,
    CandidateKind,
    SkillSnapshot,
    candidates,
    count_new,
)
from app.modules.learning.domain.mastery import (
    LAPSE_THRESHOLD,
    RETAINED_AFTER_DAYS,
    AttemptRecord,
    MasteryInputs,
    MasteryState,
    accuracy_margin,
    chance_level,
    evaluate,
    independent_ratio,
    is_delayed_pass,
    next_state,
    observed_accuracy,
    scored_attempts,
)
from app.modules.learning.domain.scheduling import (
    EASE_MAX,
    EASE_MIN,
    INTERVALS,
    days_overdue,
    quality_from_latency,
    schedule,
)

NOW = dt.datetime(2026, 6, 1, 10, 0, tzinfo=dt.UTC)


# --- scheduling -------------------------------------------------------------


def test_a_miss_always_resets_to_tomorrow() -> None:
    """Forgetting is a signal to practise sooner, never later."""
    result = schedule(interval_days=21, ease_factor=2.5, correct=False, latency_ratio=0.5, now=NOW)
    assert result.interval_days == 1
    assert result.due_at == NOW + dt.timedelta(days=1)
    assert result.ease_factor == pytest.approx(2.3)


def test_ease_factor_never_falls_below_the_floor() -> None:
    ease = 2.3
    for _ in range(20):
        ease = schedule(
            interval_days=1, ease_factor=ease, correct=False, latency_ratio=0.5, now=NOW
        ).ease_factor
    assert ease == pytest.approx(EASE_MIN)


def test_ease_factor_never_exceeds_the_cap() -> None:
    ease = 2.3
    for _ in range(50):
        ease = schedule(
            interval_days=1, ease_factor=ease, correct=True, latency_ratio=0.1, now=NOW
        ).ease_factor
    assert ease <= EASE_MAX


@pytest.mark.parametrize(
    ("ratio", "quality"), [(0.0, 5), (0.59, 5), (0.6, 4), (0.99, 4), (1.0, 3), (5.0, 3)]
)
def test_quality_from_latency(ratio: float, quality: int) -> None:
    assert quality_from_latency(ratio) == quality


def test_intervals_advance_through_the_gentled_ladder() -> None:
    interval = 1.0
    seen = [interval]
    for _ in range(len(INTERVALS) + 3):
        interval = schedule(
            interval_days=interval, ease_factor=2.3, correct=True, latency_ratio=0.1, now=NOW
        ).interval_days
        seen.append(interval)
    assert seen[-1] == INTERVALS[-1], "must cap at the longest interval"
    assert seen == sorted(seen), "intervals must never go backwards on success"


def test_the_longest_interval_is_capped_at_35_days() -> None:
    """Over-long gaps in this population produce loss, not consolidation."""
    assert max(INTERVALS) == 35


@settings(max_examples=300)
@given(
    interval=st.floats(min_value=1, max_value=100),
    ease=st.floats(min_value=1.5, max_value=2.6),
    correct=st.booleans(),
    latency=st.floats(min_value=0.0, max_value=5.0),
)
def test_schedule_always_produces_a_future_due_date_and_legal_ease(
    interval: float, ease: float, correct: bool, latency: float
) -> None:
    result = schedule(
        interval_days=interval, ease_factor=ease, correct=correct, latency_ratio=latency, now=NOW
    )
    assert result.due_at > NOW
    assert EASE_MIN <= result.ease_factor <= EASE_MAX
    assert result.interval_days >= 1


def test_days_overdue_is_never_negative() -> None:
    assert days_overdue(NOW + dt.timedelta(days=5), NOW) == 0.0
    assert days_overdue(NOW - dt.timedelta(days=2), NOW) == pytest.approx(2.0)


# --- mastery transitions ----------------------------------------------------


def test_ai_can_never_grant_mastery_only_withhold() -> None:
    """Principle P2, at the pure-logic layer.

    The database CHECK constraint is the backstop; this is the rule it backs up.
    """
    withheld = next_state(
        MasteryState.PRACTISING, rule_satisfied=True, p_known=0.95, ai_withholds=True
    )
    assert withheld is not MasteryState.MASTERED

    # And with the rule unmet, no value of ai_withholds produces mastery.
    for withholds in (True, False):
        assert (
            next_state(
                MasteryState.PRACTISING,
                rule_satisfied=False,
                p_known=0.99,
                ai_withholds=withholds,
            )
            is not MasteryState.MASTERED
        )


def test_the_progression_ladder() -> None:
    state = MasteryState.NOT_STARTED
    state = next_state(state, rule_satisfied=False, p_known=0.2)
    assert state is MasteryState.INTRODUCED
    state = next_state(state, rule_satisfied=False, p_known=0.5)
    assert state is MasteryState.PRACTISING
    state = next_state(state, rule_satisfied=False, p_known=0.8)
    assert state is MasteryState.PRACTISING
    state = next_state(state, rule_satisfied=True, p_known=0.95)
    assert state is MasteryState.MASTERED


def test_a_mastered_skill_lapses_when_p_known_decays() -> None:
    lapsed = next_state(MasteryState.MASTERED, rule_satisfied=True, p_known=LAPSE_THRESHOLD - 0.01)
    assert lapsed is MasteryState.LAPSED
    held = next_state(MasteryState.MASTERED, rule_satisfied=True, p_known=LAPSE_THRESHOLD)
    assert held is MasteryState.MASTERED


def test_retained_requires_three_weeks_and_a_still_satisfied_rule() -> None:
    mastered_at = NOW - dt.timedelta(days=RETAINED_AFTER_DAYS)
    retained = next_state(
        MasteryState.MASTERED,
        rule_satisfied=True,
        p_known=0.95,
        mastered_at=mastered_at,
        now=NOW,
    )
    assert retained is MasteryState.RETAINED

    too_soon = next_state(
        MasteryState.MASTERED,
        rule_satisfied=True,
        p_known=0.95,
        mastered_at=NOW - dt.timedelta(days=RETAINED_AFTER_DAYS - 1),
        now=NOW,
    )
    assert too_soon is MasteryState.MASTERED

    # A skill whose rule no longer holds does not get promoted to retained.
    not_promoted = next_state(
        MasteryState.MASTERED,
        rule_satisfied=False,
        p_known=0.95,
        mastered_at=mastered_at,
        now=NOW,
    )
    assert not_promoted is MasteryState.MASTERED


def test_a_retained_skill_can_still_lapse() -> None:
    assert (
        next_state(MasteryState.RETAINED, rule_satisfied=True, p_known=0.5) is MasteryState.LAPSED
    )


def test_a_lapsed_skill_can_be_re_mastered() -> None:
    assert (
        next_state(MasteryState.LAPSED, rule_satisfied=True, p_known=0.95) is MasteryState.MASTERED
    )


# --- mastery rule components ------------------------------------------------


def _attempt(
    correct: bool, level: PromptLevel = PromptLevel.INDEPENDENT, n: int = 2
) -> AttemptRecord:
    return AttemptRecord(correct=correct, prompt_level=level, choice_count=n, at=NOW)


def test_independent_ratio_of_no_attempts_is_zero_not_one() -> None:
    """No evidence is not perfect evidence."""
    assert independent_ratio([]) == 0.0


def test_independent_ratio_counts_only_unprompted_responses() -> None:
    attempts = [
        _attempt(True),
        _attempt(True),
        _attempt(True, PromptLevel.GESTURAL),
        _attempt(True, PromptLevel.FULL_MODEL),
    ]
    assert independent_ratio(attempts) == pytest.approx(0.5)


def test_full_model_attempts_are_excluded_from_accuracy() -> None:
    """Otherwise the prompt ladder would inflate accuracy to 100%."""
    attempts = [_attempt(False)] + [_attempt(True, PromptLevel.FULL_MODEL) for _ in range(9)]
    assert len(scored_attempts(attempts)) == 1
    assert observed_accuracy(attempts) == 0.0


def test_accuracy_and_chance_of_an_empty_history() -> None:
    assert observed_accuracy([]) == 0.0
    assert chance_level([]) == 0.5
    assert chance_level([_attempt(True, PromptLevel.FULL_MODEL)]) == 0.5


def test_chance_level_is_averaged_over_the_real_choice_counts() -> None:
    attempts = [_attempt(True, n=2), _attempt(True, n=4)]
    assert chance_level(attempts) == pytest.approx((0.5 + 0.25) / 2)


def test_accuracy_margin_shrinks_with_evidence_and_grows_with_looks() -> None:
    assert accuracy_margin(window_size=40, total_looks=40) < accuracy_margin(
        window_size=10, total_looks=40
    )
    assert accuracy_margin(window_size=40, total_looks=500) > accuracy_margin(
        window_size=40, total_looks=40
    )
    # A degenerate window can never be satisfied.
    assert accuracy_margin(window_size=0, total_looks=10) == 1.0


def test_evaluate_names_every_unmet_condition() -> None:
    decision = evaluate(
        MasteryInputs(
            p_known=0.5,
            distinct_days=1,
            first_correct_at=None,
            last_delayed_pass_at=None,
            attempts=[],
        )
    )
    assert not decision.satisfied
    assert set(decision.unmet) == {
        "p_known",
        "distinct_days",
        "delayed_pass",
        "independent_ratio",
        "min_scored_attempts",
    }


def test_a_short_history_withholds_rather_than_guessing() -> None:
    decision = evaluate(
        MasteryInputs(
            p_known=0.99,
            distinct_days=5,
            first_correct_at=NOW,
            last_delayed_pass_at=NOW,
            attempts=[_attempt(True) for _ in range(5)],
        )
    )
    assert "min_scored_attempts" in decision.unmet


@pytest.mark.parametrize(
    ("correct", "days", "expected"),
    [(True, 3, True), (True, 2, False), (False, 10, False), (True, 30, True)],
)
def test_is_delayed_pass(correct: bool, days: int, expected: bool) -> None:
    assert (
        is_delayed_pass(first_correct_at=NOW, at=NOW + dt.timedelta(days=days), correct=correct)
        is expected
    )


def test_is_delayed_pass_needs_a_first_correct() -> None:
    assert not is_delayed_pass(first_correct_at=None, at=NOW, correct=True)


# --- candidate composition --------------------------------------------------


def _snapshot(
    skill_id: str,
    state: MasteryState,
    *,
    due: dt.datetime | None = None,
    order: int = 0,
    tier: int = 1,
    prerequisites: tuple[str, ...] = (),
    pgee: bool = False,
) -> SkillSnapshot:
    return SkillSnapshot(
        skill_id=skill_id,
        modality="receptive",
        state=state,
        due_at=due,
        intro_order=order,
        difficulty_tier=tier,
        prerequisites=prerequisites,
        pgee_linked=pgee,
    )


def test_never_more_than_one_new_skill() -> None:
    """P07: candidates() never returns two new skills."""
    snapshots = [_snapshot(f"new{i}", MasteryState.NOT_STARTED, order=i) for i in range(10)]
    assert count_new(candidates(snapshots, now=NOW)) == MAX_NEW


def test_no_new_skill_at_all_when_three_are_practising() -> None:
    """P07: zero new skills when three are practising.

    Introducing a competing item mid-flight is how you get interference in this
    population — this is a clinical rule, not a product preference.
    """
    snapshots = [
        *[
            _snapshot(f"p{i}", MasteryState.PRACTISING, due=NOW, order=i)
            for i in range(PRACTISING_BLOCKS_NEW)
        ],
        _snapshot("new", MasteryState.NOT_STARTED, order=99),
    ]
    assert count_new(candidates(snapshots, now=NOW)) == 0


def test_two_practising_still_allows_one_new_skill() -> None:
    snapshots = [
        *[_snapshot(f"p{i}", MasteryState.PRACTISING, due=NOW, order=i) for i in range(2)],
        _snapshot("new", MasteryState.NOT_STARTED, order=99),
    ]
    assert count_new(candidates(snapshots, now=NOW)) == 1


def test_lapsed_skills_come_first() -> None:
    snapshots = [
        _snapshot("due", MasteryState.PRACTISING, due=NOW - dt.timedelta(days=1)),
        _snapshot("lapsed", MasteryState.LAPSED),
    ]
    selected = candidates(snapshots, now=NOW)
    assert selected[0].skill_id == "lapsed"
    assert selected[0].kind is CandidateKind.LAPSED


def test_the_session_ends_on_a_mastered_skill() -> None:
    """Always end on a win."""
    snapshots = [
        _snapshot("due", MasteryState.PRACTISING, due=NOW),
        _snapshot("won", MasteryState.MASTERED),
    ]
    selected = candidates(snapshots, now=NOW)
    assert selected[-1].kind is CandidateKind.CONFIDENCE
    assert selected[-1].skill_id == "won"


def test_a_new_skill_with_unmet_prerequisites_is_not_offered() -> None:
    snapshots = [
        _snapshot("locked", MasteryState.NOT_STARTED, prerequisites=("missing",)),
        _snapshot("open", MasteryState.NOT_STARTED, order=5),
    ]
    selected = candidates(snapshots, now=NOW)
    new_ids = {c.skill_id for c in selected if c.kind is CandidateKind.NEW}
    assert new_ids == {"open"}


def test_a_prerequisite_satisfied_by_a_retained_skill_unlocks_the_next() -> None:
    snapshots = [
        _snapshot("base", MasteryState.RETAINED),
        _snapshot("next", MasteryState.NOT_STARTED, prerequisites=("base",)),
    ]
    selected = candidates(snapshots, now=NOW)
    assert "next" in {c.skill_id for c in selected if c.kind is CandidateKind.NEW}


def test_a_pgee_linked_skill_outranks_intro_order() -> None:
    """The assessment's own recommendation comes first among equals."""
    snapshots = [
        _snapshot("early", MasteryState.NOT_STARTED, order=1),
        _snapshot("from_pgee", MasteryState.NOT_STARTED, order=50, pgee=True),
    ]
    selected = candidates(snapshots, now=NOW)
    new = [c for c in selected if c.kind is CandidateKind.NEW]
    assert new[0].skill_id == "from_pgee"


def test_a_skill_not_yet_due_is_not_reviewed() -> None:
    snapshots = [_snapshot("later", MasteryState.PRACTISING, due=NOW + dt.timedelta(days=3))]
    assert candidates(snapshots, now=NOW) == []


def test_the_overall_cap_is_respected() -> None:
    snapshots = [_snapshot(f"due{i}", MasteryState.PRACTISING, due=NOW, order=i) for i in range(20)]
    snapshots += [_snapshot(f"lap{i}", MasteryState.LAPSED, order=i) for i in range(5)]
    snapshots += [_snapshot(f"m{i}", MasteryState.MASTERED, order=i) for i in range(5)]
    selected = candidates(snapshots, now=NOW, limit=8)
    assert len(selected) <= 8


def test_no_skill_appears_twice() -> None:
    """A skill that is both due and mastered must not be scheduled twice."""
    snapshots = [
        _snapshot("dup", MasteryState.MASTERED, due=NOW - dt.timedelta(days=1)),
        _snapshot("other", MasteryState.PRACTISING, due=NOW),
    ]
    selected = candidates(snapshots, now=NOW)
    ids = [c.skill_id for c in selected]
    assert len(ids) == len(set(ids))


def test_an_empty_curriculum_produces_no_candidates() -> None:
    assert candidates([], now=NOW) == []


@settings(max_examples=200)
@given(
    states=st.lists(st.sampled_from(list(MasteryState)), min_size=0, max_size=30),
    limit=st.integers(min_value=1, max_value=12),
)
def test_candidate_invariants_hold_for_any_curriculum(
    states: list[MasteryState], limit: int
) -> None:
    snapshots = [_snapshot(f"s{i}", state, due=NOW, order=i) for i, state in enumerate(states)]
    selected = candidates(snapshots, now=NOW, limit=limit)

    assert len(selected) <= limit
    assert count_new(selected) <= MAX_NEW
    ids = [(c.skill_id, c.modality) for c in selected]
    assert len(ids) == len(set(ids))

    practising = sum(1 for s in states if s is MasteryState.PRACTISING)
    if practising >= PRACTISING_BLOCKS_NEW:
        assert count_new(selected) == 0


def test_a_duplicated_snapshot_is_scheduled_only_once() -> None:
    """A bad join upstream must not put the same activity in twice.

    The four selection buckets are disjoint by state, so the dedupe only fires
    when the input itself contains the same (skill, modality) twice. That is a
    data-quality failure, not a normal path — and the child should still get a
    coherent session.
    """
    duplicated = _snapshot("same", MasteryState.LAPSED, order=1)
    selected = candidates([duplicated, duplicated], now=NOW)
    assert [c.skill_id for c in selected] == ["same"]
