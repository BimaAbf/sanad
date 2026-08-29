"""Pure child-profile logic. No I/O.

`age_months` is the load-bearing function: it feeds the assessment entry bands,
and an error here shifts every developmental-age figure the caregiver ever sees.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum
from zoneinfo import ZoneInfo

#: Ages are computed in the family's civil day, not UTC. Cairo is UTC+2/+3, so a
#: child created at 01:00 local on their birthday would otherwise be recorded as
#: a day younger.
PRODUCT_TZ = ZoneInfo("Africa/Cairo")


def today() -> dt.date:
    return dt.datetime.now(PRODUCT_TZ).date()


#: Mean days per month over a 4-year cycle: 365.25 / 12. Using 30 or 30.5 drifts
#: by roughly a fortnight over four years, which is a whole assessment band.
DAYS_PER_MONTH = 30.4375

#: Below this many weeks a birth is preterm and correction applies.
TERM_WEEKS = 37

#: Correction stops at 24 months chronological — the standard convention, and
#: the one docs/04a §C02 specifies.
CORRECTION_CUTOFF_MONTHS = 24

#: A child outside this range cannot be onboarded (docs/04a §C02 edge cases).
MAX_AGE_YEARS = 8

#: Preterm birth is not recorded below 22 weeks; anything lower is a typo.
MIN_GESTATIONAL_WEEKS = 22
MAX_GESTATIONAL_WEEKS = 45


class ConsentKey(StrEnum):
    """The seven keys seeded in docs/02 §3."""

    DATA_PROCESSING = "data_processing"
    AI_PROCESSING = "ai_processing"
    TERMS_NOT_MEDICAL = "terms_not_medical"
    VOICE_ASR = "voice_asr"
    VOICE_RETENTION = "voice_retention"
    CLINICIAN_SHARE = "clinician_share"
    RESEARCH_AGGREGATE = "research_aggregate"


#: Without all three there is no service at all (docs/07 §4 legal basis table).
MANDATORY_CONSENTS: frozenset[ConsentKey] = frozenset(
    {
        ConsentKey.DATA_PROCESSING,
        ConsentKey.AI_PROCESSING,
        ConsentKey.TERMS_NOT_MEDICAL,
    }
)


@dataclass(frozen=True, slots=True)
class Age:
    chronological_months: float
    corrected_months: float

    @property
    def is_corrected(self) -> bool:
        return self.corrected_months < self.chronological_months


def age_months(dob: dt.date, today: dt.date, gestational_weeks: int | None) -> Age:
    """Chronological and corrected age in months.

    Transcribed from docs/04a §C02. Correction subtracts the number of weeks the
    child was born early, and applies only while chronological age is under 24
    months. It never returns a negative age: a 24-weeker on their day of birth is
    0.0 corrected, not -3.

    Assessment entry bands use the *corrected* figure; the report shows both.
    """
    chrono = (today - dob).days / DAYS_PER_MONTH
    if (
        gestational_weeks is not None
        and gestational_weeks < TERM_WEEKS
        and chrono < CORRECTION_CUTOFF_MONTHS
    ):
        correction = (TERM_WEEKS - gestational_weeks) * 7 / DAYS_PER_MONTH
        return Age(chrono, max(chrono - correction, 0.0))
    return Age(chrono, chrono)


class DobProblem(StrEnum):
    IN_FUTURE = "in_future"
    TOO_OLD = "too_old"


def check_dob(dob: dt.date, today: dt.date) -> DobProblem | None:
    if dob > today:
        return DobProblem.IN_FUTURE
    if (today - dob).days / DAYS_PER_MONTH > MAX_AGE_YEARS * 12:
        return DobProblem.TOO_OLD
    return None


def check_gestational_weeks(weeks: int | None) -> bool:
    if weeks is None:
        return True
    return MIN_GESTATIONAL_WEEKS <= weeks <= MAX_GESTATIONAL_WEEKS


def missing_mandatory_consents(granted: set[str]) -> list[ConsentKey]:
    """Which mandatory consents are absent. Empty means the child may be created."""
    return sorted(
        (key for key in MANDATORY_CONSENTS if key.value not in granted),
        key=lambda key: key.value,
    )
