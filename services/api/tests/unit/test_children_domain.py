"""Corrected-age and consent logic.

`age_months` feeds the assessment entry bands, so an error here shifts every
developmental-age figure a caregiver ever sees. The acceptance criteria from
P02 are asserted verbatim.
"""

from __future__ import annotations

import datetime as dt

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.modules.children import domain

# --- P02 acceptance criteria, verbatim -------------------------------------


def test_born_at_32_weeks_18_months_chronological_is_1685_corrected() -> None:
    """P02: 'born at 32 weeks, now 18 months chronological → 16.85 corrected'.

    Hand check: 37 - 32 = 5 weeks early. 5 * 7 = 35 days.
    35 / 30.4375 = 1.14989... months. 18 - 1.14989 = 16.85011.
    """
    dob = dt.date(2025, 1, 1)
    today = dob + dt.timedelta(days=round(18 * domain.DAYS_PER_MONTH))
    age = domain.age_months(dob, today, gestational_weeks=32)
    assert age.chronological_months == pytest.approx(18.0, abs=0.02)
    assert age.corrected_months == pytest.approx(16.85, abs=0.05)
    assert age.is_corrected


def test_at_26_months_chronological_correction_no_longer_applies() -> None:
    """P02: 'at 26 months chronological, corrected == chronological'."""
    dob = dt.date(2024, 1, 1)
    today = dob + dt.timedelta(days=round(26 * domain.DAYS_PER_MONTH))
    age = domain.age_months(dob, today, gestational_weeks=32)
    assert age.corrected_months == age.chronological_months
    assert not age.is_corrected


def test_correction_boundary_is_exactly_24_months() -> None:
    dob = dt.date(2024, 1, 1)
    just_under = dob + dt.timedelta(days=int(24 * domain.DAYS_PER_MONTH) - 1)
    just_over = dob + dt.timedelta(days=int(24 * domain.DAYS_PER_MONTH) + 2)
    assert domain.age_months(dob, just_under, 30).is_corrected
    assert not domain.age_months(dob, just_over, 30).is_corrected


# --- correction rules ------------------------------------------------------


@pytest.mark.parametrize("weeks", [37, 38, 40, 42, None])
def test_term_and_unknown_gestation_are_never_corrected(weeks: int | None) -> None:
    dob = dt.date(2025, 1, 1)
    today = dt.date(2025, 7, 1)
    age = domain.age_months(dob, today, weeks)
    assert age.corrected_months == age.chronological_months


def test_correction_never_produces_a_negative_age() -> None:
    """A 24-weeker on their day of birth is 0.0 corrected, not -3."""
    dob = dt.date(2026, 8, 29)
    age = domain.age_months(dob, dob, gestational_weeks=24)
    assert age.chronological_months == 0.0
    assert age.corrected_months == 0.0


def test_earlier_birth_means_larger_correction() -> None:
    dob = dt.date(2025, 1, 1)
    today = dt.date(2025, 10, 1)
    ages = [domain.age_months(dob, today, w).corrected_months for w in (36, 34, 30, 26)]
    assert ages == sorted(ages, reverse=True), "earlier gestation must correct further down"


# --- properties ------------------------------------------------------------


@settings(max_examples=400)
@given(
    dob=st.dates(min_value=dt.date(2018, 1, 1), max_value=dt.date(2026, 8, 29)),
    offset_a=st.integers(min_value=0, max_value=2900),
    extra=st.integers(min_value=0, max_value=400),
    weeks=st.one_of(st.none(), st.integers(min_value=22, max_value=45)),
)
def test_age_is_monotonically_non_decreasing_in_today(
    dob: dt.date, offset_a: int, extra: int, weeks: int | None
) -> None:
    """P02 property: age_months is non-decreasing in `today` for any dob.

    Both figures must be non-decreasing. Corrected age is the subtle one: it
    tracks chronological until the 24-month cutoff, then steps *up* to meet it.
    It must never step down.
    """
    today_a = dob + dt.timedelta(days=offset_a)
    today_b = today_a + dt.timedelta(days=extra)
    age_a = domain.age_months(dob, today_a, weeks)
    age_b = domain.age_months(dob, today_b, weeks)
    assert age_b.chronological_months >= age_a.chronological_months
    assert age_b.corrected_months >= age_a.corrected_months


@settings(max_examples=300)
@given(
    dob=st.dates(min_value=dt.date(2018, 1, 1), max_value=dt.date(2026, 8, 29)),
    offset=st.integers(min_value=0, max_value=2900),
    weeks=st.one_of(st.none(), st.integers(min_value=22, max_value=45)),
)
def test_corrected_never_exceeds_chronological_and_neither_is_negative(
    dob: dt.date, offset: int, weeks: int | None
) -> None:
    age = domain.age_months(dob, dob + dt.timedelta(days=offset), weeks)
    assert 0.0 <= age.corrected_months <= age.chronological_months


@given(offset=st.integers(min_value=1, max_value=3000))
def test_chronological_age_is_days_over_30_4375(offset: int) -> None:
    dob = dt.date(2020, 6, 15)
    age = domain.age_months(dob, dob + dt.timedelta(days=offset), None)
    assert age.chronological_months == pytest.approx(offset / 30.4375)


# --- date-of-birth validation ----------------------------------------------


def test_future_dob_is_rejected() -> None:
    today = dt.date(2026, 8, 29)
    assert domain.check_dob(today + dt.timedelta(days=1), today) is domain.DobProblem.IN_FUTURE
    assert domain.check_dob(today, today) is None


def test_over_eight_years_is_rejected() -> None:
    today = dt.date(2026, 8, 29)
    ok = today - dt.timedelta(days=int(8 * 365.25) - 5)
    too_old = today - dt.timedelta(days=int(8 * 365.25) + 30)
    assert domain.check_dob(ok, today) is None
    assert domain.check_dob(too_old, today) is domain.DobProblem.TOO_OLD


@pytest.mark.parametrize(
    ("weeks", "ok"),
    [(None, True), (22, True), (40, True), (45, True), (21, False), (46, False), (0, False)],
)
def test_gestational_week_bounds(weeks: int | None, ok: bool) -> None:
    assert domain.check_gestational_weeks(weeks) is ok


# --- consent ---------------------------------------------------------------


def test_the_three_mandatory_consents_are_exactly_as_documented() -> None:
    assert {k.value for k in domain.MANDATORY_CONSENTS} == {
        "data_processing",
        "ai_processing",
        "terms_not_medical",
    }


def test_there_are_seven_consent_keys() -> None:
    assert len(list(domain.ConsentKey)) == 7


def test_missing_mandatory_consents_is_empty_only_when_all_three_are_granted() -> None:
    assert domain.missing_mandatory_consents(set()) == sorted(
        domain.MANDATORY_CONSENTS, key=lambda k: k.value
    )
    assert domain.missing_mandatory_consents({"data_processing"}) == [
        domain.ConsentKey.AI_PROCESSING,
        domain.ConsentKey.TERMS_NOT_MEDICAL,
    ]
    assert (
        domain.missing_mandatory_consents({"data_processing", "ai_processing", "terms_not_medical"})
        == []
    )


def test_optional_consents_alone_do_not_satisfy_the_mandatory_set() -> None:
    optional = {"voice_asr", "voice_retention", "clinician_share", "research_aggregate"}
    assert len(domain.missing_mandatory_consents(optional)) == 3


@given(granted=st.sets(st.sampled_from([k.value for k in domain.ConsentKey])))
def test_missing_is_exactly_the_mandatory_keys_not_granted(granted: set[str]) -> None:
    assume(True)
    missing = set(domain.missing_mandatory_consents(granted))
    assert missing == {k for k in domain.MANDATORY_CONSENTS if k.value not in granted}
