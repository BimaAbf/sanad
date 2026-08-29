"""T10 — progress rollups and the three product rules.

The headline test is the first one: a 30-session synthetic history run through
both the incremental and the nightly path, diffed field by field. docs/04a §C09
calls the nightly rebuild "the correctness backstop for the incremental path",
and a backstop nobody compares against is decoration.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.modules.progress.domain.periods import (
    ALL_TIME,
    day_key,
    local_date,
    month_key,
    next_month,
    parse_day,
    partition_bounds,
    periods_for,
    week_key,
)
from app.modules.progress.domain.rollup import (
    Rollup,
    SessionFact,
    SkillStateFact,
    compute,
    count_states,
    diff,
    group_by_period,
    rebuild_all,
    rebuild_for_session,
)
from app.modules.progress.domain.views import (
    FORBIDDEN_DASHBOARD_FIELDS,
    MIN_POINTS_FOR_TREND,
    REVISIT_ACTIVITIES,
    Activity,
    AssessmentPoint,
    SkillCard,
    build_journey,
    build_revisit_plan,
    build_skills,
    build_today,
    detect_regression,
    streak_days,
)

CAIRO_NOON = dt.datetime(2026, 8, 29, 10, 0, tzinfo=dt.UTC)  # 12:00 Cairo


def session(
    index: int, *, day_offset: int, attempts: int = 10, correct: int = 7, minutes: int = 8
) -> SessionFact:
    return SessionFact(
        session_id=f"s{index}",
        child_id="c1",
        started_at=CAIRO_NOON - dt.timedelta(days=day_offset),
        minutes=minutes,
        attempts=attempts,
        correct=correct,
        by_category={"colors": attempts // 2, "household": attempts - attempts // 2},
    )


STATES = [
    SkillStateFact("k1", "colors", "mastered"),
    SkillStateFact("k2", "colors", "retained"),
    SkillStateFact("k3", "household", "practising"),
    SkillStateFact("k4", "household", "emerging"),
    SkillStateFact("k5", "letters", "not_started"),
]


# --- the backstop ----------------------------------------------------------


def thirty_session_history() -> list[SessionFact]:
    """30 sessions spread over 6 weeks, several on the same day, one gap week.

    Same-day sessions and a gap are both included deliberately: they are the two
    shapes where an incremental path that adds a delta silently diverges.
    """
    offsets = (
        0,
        0,
        1,
        2,
        3,
        5,
        6,
        7,
        8,
        9,
        10,
        12,
        13,
        14,
        15,
        16,
        20,
        21,
        22,
        23,
        24,
        30,
        31,
        32,
        33,
        34,
        35,
        38,
        39,
        40,
    )
    return [
        session(index, day_offset=offset, attempts=5 + index % 7, correct=index % 5)
        for index, offset in enumerate(offsets)
    ]


def test_incremental_and_nightly_agree_over_thirty_sessions() -> None:
    """T10 §1. Run both, diff, assert zero difference."""
    history = thirty_session_history()
    assert len(history) == 30

    nightly = rebuild_all(child_id="c1", sessions=history, states=STATES)

    # Replay the incremental path exactly as production would: one call per
    # session end, in order, each seeing the sessions completed so far.
    incremental: dict[tuple[str, str], Rollup] = {}
    for position, current in enumerate(history, start=1):
        for rollup in rebuild_for_session(
            child_id="c1",
            session=current,
            all_sessions=history[:position],
            states=STATES,
        ):
            incremental[rollup.key()] = rollup

    assert diff(nightly, list(incremental.values())) == []


def test_the_diff_helper_actually_reports_differences() -> None:
    """A comparison that cannot fail proves nothing about the one that passed."""
    left = compute(
        child_id="c1", period=ALL_TIME, sessions=[session(0, day_offset=0)], states=STATES
    )
    right = compute(child_id="c1", period=ALL_TIME, sessions=[], states=STATES)
    problems = diff([left], [right])
    assert any("attempts" in problem for problem in problems)
    assert diff([left], []) == [f"{ALL_TIME}: present in only one set"]


def test_replaying_the_rollup_changes_nothing() -> None:
    """T10 §2 — idempotence, which here is structural rather than guarded.

    Both paths recompute a period in full from its member sessions, so running
    either twice produces the same rows by construction.
    """
    history = thirty_session_history()
    once = rebuild_all(child_id="c1", sessions=history, states=STATES)
    twice = rebuild_all(child_id="c1", sessions=history, states=STATES)
    assert diff(once, twice) == []

    current = history[-1]
    a = rebuild_for_session(child_id="c1", session=current, all_sessions=history, states=STATES)
    b = rebuild_for_session(child_id="c1", session=current, all_sessions=history, states=STATES)
    assert diff(a, b) == []


def test_a_period_with_no_attempts_has_no_accuracy_rather_than_zero() -> None:
    """0% accuracy for a week with no play tells a parent their child failed
    everything. It is not a rounding decision."""
    rollup = compute(child_id="c1", period=ALL_TIME, sessions=[], states=STATES)
    assert rollup.accuracy is None
    assert rollup.attempts == 0


def test_categories_are_summed_across_sessions() -> None:
    rollup = compute(
        child_id="c1",
        period=ALL_TIME,
        sessions=[session(0, day_offset=0, attempts=10), session(1, day_offset=0, attempts=10)],
        states=STATES,
    )
    assert rollup.by_category == {"colors": 10, "household": 10}


def test_mastered_counts_include_retained_and_practising_includes_emerging() -> None:
    mastered, practising = count_states(STATES)
    assert (mastered, practising) == (2, 2)


def test_a_session_contributes_to_day_week_and_all() -> None:
    grouped = group_by_period([session(0, day_offset=0)])
    assert set(grouped) == {day_key(CAIRO_NOON), week_key(CAIRO_NOON), ALL_TIME}


# --- period keys -----------------------------------------------------------


def test_the_day_is_the_familys_civil_day_not_utc() -> None:
    """01:00 Cairo is 23:00 UTC the previous day. Rolling that into yesterday
    breaks a streak for a family that did nothing wrong."""
    late = dt.datetime(2026, 8, 29, 23, 0, tzinfo=dt.UTC)  # 01:00 Cairo on the 30th
    assert local_date(late) == dt.date(2026, 8, 30)
    assert day_key(late) == "day:2026-08-30"


def test_a_naive_timestamp_is_treated_as_utc() -> None:
    naive = dt.datetime(2026, 8, 29, 23, 0)  # noqa: DTZ001 -- naive on purpose
    assert local_date(naive) == dt.date(2026, 8, 30)


def test_period_key_shapes() -> None:
    date = dt.date(2026, 8, 29)
    assert day_key(date) == "day:2026-08-29"
    assert week_key(date) == "week:2026-W35"
    assert periods_for(CAIRO_NOON) == ("day:2026-08-29", "week:2026-W35", "all")
    assert parse_day("day:2026-08-29") == date


def test_partition_helpers() -> None:
    assert month_key(dt.date(2026, 8, 29)) == "2026_08"
    assert next_month(dt.date(2026, 12, 3)) == dt.date(2027, 1, 1)
    assert next_month(dt.date(2026, 1, 3)) == dt.date(2026, 2, 1)
    assert partition_bounds(dt.date(2026, 8, 29)) == (dt.date(2026, 8, 1), dt.date(2026, 9, 1))


# --- rule 1: no trend before three points ---------------------------------


def point(offset_days: int, *, da: float = 24.0, mastered: int = 5) -> AssessmentPoint:
    return AssessmentPoint(
        assessment_id=f"a{offset_days}",
        completed_at=dt.date(2026, 8, 29) - dt.timedelta(days=offset_days),
        domain_da={"communication": da, "motor": da + 1},
        skills_mastered=mastered,
    )


@pytest.mark.parametrize("count", [0, 1, 2])
def test_journey_returns_insufficient_data_below_three_assessments(count: int) -> None:
    """T10 §4. A two-point trend in a developmental measure is noise."""
    view = build_journey([point(index * 180) for index in range(count)])
    assert view.status == "insufficient_data"
    assert view.points == ()
    assert view.copy_key


def test_journey_returns_points_at_three_assessments() -> None:
    view = build_journey([point(360), point(180), point(0)])
    assert view.status == "ok"
    assert len(view.points) == MIN_POINTS_FOR_TREND
    # Ordered oldest first regardless of input order.
    assert [p.completed_at for p in view.points] == sorted(p.completed_at for p in view.points)


# --- rule 2: no percentile, no DQ -----------------------------------------


def test_no_progress_schema_carries_a_norm_field() -> None:
    """T10 §3, over the module's own schemas.

    The whole-OpenAPI version of this lives in test_openapi_guards.py so a
    future endpoint in another module cannot slip one through either.
    """
    from pydantic import BaseModel

    from app.modules.progress import schemas

    for name in dir(schemas):
        candidate = getattr(schemas, name)
        if not (isinstance(candidate, type) and issubclass(candidate, BaseModel)):
            continue
        offending = set(candidate.model_fields) & FORBIDDEN_DASHBOARD_FIELDS
        assert offending == set(), f"{name} exposes {offending}"


# --- rule 3: regression always carries a plan ------------------------------


CANDIDATES = [
    Activity("listen_point_2choice", "k1", "أحمر"),
    Activity("listen_point_2choice", "k2", "أزرق"),
    Activity("match_pair_picture", "k3", "شوكة"),
    Activity("listen_point_3choice", "k4", "كرسي"),
]


def test_a_regression_returns_exactly_three_activities() -> None:
    """T10 §5."""
    yesterday = Rollup("c1", "day:2026-08-28", 1, 8, 10, 0.7, 5, 3, {})
    today = Rollup("c1", "day:2026-08-29", 1, 8, 10, 0.7, 4, 3, {})
    view = build_today(
        today=dt.date(2026, 8, 29),
        day_rollup=today,
        previous_day_rollup=yesterday,
        history=[today, yesterday],
        suggestion=None,
        revisit_candidates=CANDIDATES,
    )
    assert view.regression_detected
    assert len(view.revisit_plan) == REVISIT_ACTIVITIES


def test_no_regression_means_no_plan() -> None:
    yesterday = Rollup("c1", "day:2026-08-28", 1, 8, 10, 0.7, 3, 3, {})
    today = Rollup("c1", "day:2026-08-29", 1, 8, 10, 0.7, 5, 3, {})
    view = build_today(
        today=dt.date(2026, 8, 29),
        day_rollup=today,
        previous_day_rollup=yesterday,
        history=[today, yesterday],
        suggestion=None,
        revisit_candidates=CANDIDATES,
    )
    assert not view.regression_detected
    assert view.revisit_plan == ()


def test_a_regression_with_too_few_candidates_is_not_surfaced_at_all() -> None:
    """One or two activities would be worse than none: it presents a regression
    AND an inadequate answer to it."""
    assert build_revisit_plan(CANDIDATES[:2]) == ()
    yesterday = Rollup("c1", "day:2026-08-28", 1, 8, 10, 0.7, 5, 3, {})
    today = Rollup("c1", "day:2026-08-29", 1, 8, 10, 0.7, 4, 3, {})
    view = build_today(
        today=dt.date(2026, 8, 29),
        day_rollup=today,
        previous_day_rollup=yesterday,
        history=[],
        suggestion=None,
        revisit_candidates=CANDIDATES[:2],
    )
    assert view.revisit_plan == ()
    # The bare negative signal must not survive on its own.
    assert not view.regression_detected


def test_a_falling_domain_developmental_age_counts_as_a_regression() -> None:
    points = [point(360, da=24.0), point(180, da=26.0), point(0, da=25.0)]
    assert detect_regression(current=None, previous=None, points=points)
    view = build_journey(points, revisit_candidates=CANDIDATES)
    assert len(view.revisit_plan) == REVISIT_ACTIVITIES


def test_a_rising_domain_age_is_not_a_regression() -> None:
    points = [point(360, da=22.0), point(180, da=24.0), point(0, da=26.0)]
    assert not detect_regression(current=None, previous=None, points=points)
    assert build_journey(points, revisit_candidates=CANDIDATES).revisit_plan == ()


def test_a_new_domain_appearing_is_not_a_regression() -> None:
    earlier = AssessmentPoint("a1", dt.date(2026, 1, 1), {"motor": 20.0}, 3)
    later = AssessmentPoint("a2", dt.date(2026, 6, 1), {"motor": 22.0, "social": 18.0}, 4)
    assert not detect_regression(current=None, previous=None, points=[earlier, later])


# --- streaks ---------------------------------------------------------------


def rollup_for(date: dt.date, sessions: int = 1) -> Rollup:
    return Rollup("c1", day_key(date), sessions, 8, 10, 0.7, 3, 2, {})


def test_streak_counts_consecutive_days() -> None:
    today = dt.date(2026, 8, 29)
    history = [rollup_for(today - dt.timedelta(days=offset)) for offset in range(4)]
    assert streak_days(history, today=today) == 4


def test_a_streak_survives_until_the_end_of_the_next_day() -> None:
    """Breaking a streak at midnight punishes a family for the clock."""
    today = dt.date(2026, 8, 29)
    history = [rollup_for(today - dt.timedelta(days=offset)) for offset in (1, 2, 3)]
    assert streak_days(history, today=today) == 3


def test_a_two_day_gap_breaks_the_streak() -> None:
    today = dt.date(2026, 8, 29)
    history = [rollup_for(today - dt.timedelta(days=offset)) for offset in (2, 3, 4)]
    assert streak_days(history, today=today) == 0


def test_no_play_at_all_is_a_zero_streak() -> None:
    assert streak_days([], today=dt.date(2026, 8, 29)) == 0
    assert (
        streak_days([rollup_for(dt.date(2026, 8, 29), sessions=0)], today=dt.date(2026, 8, 29)) == 0
    )


def test_non_day_periods_are_ignored_by_the_streak() -> None:
    history = [Rollup("c1", ALL_TIME, 9, 60, 90, 0.7, 3, 2, {})]
    assert streak_days(history, today=dt.date(2026, 8, 29)) == 0


# --- the skills map --------------------------------------------------------


def card(code: str, category: str, state: str) -> SkillCard:
    return SkillCard(
        skill_id=f"id_{code}", code=code, label_ar=code, category=category, state=state, p_known=0.5
    )


def test_skills_view_groups_and_counts() -> None:
    cards = [
        card("color_red", "colors", "mastered"),
        card("color_blue", "colors", "retained"),
        card("hh_fork", "household", "practising"),
        card("hh_cup", "household", "not_started"),
        card("letter_alef", "letters", "not_started"),
    ]
    view = build_skills(cards)
    assert view.total == 5
    assert view.mastered == 2
    assert view.practising == 1
    assert view.not_started == 2
    assert list(view.by_category) == ["colors", "household", "letters"]
    assert [c.code for c in view.by_category["colors"]] == ["color_blue", "color_red"]


def test_today_view_with_no_rollup_at_all() -> None:
    view = build_today(
        today=dt.date(2026, 8, 29),
        day_rollup=None,
        previous_day_rollup=None,
        history=[],
        suggestion=None,
    )
    assert (view.sessions, view.minutes, view.attempts) == (0, 0, 0)
    assert view.streak_days == 0
    assert not view.regression_detected
