"""Six hand-computed scoring scenarios, one per domain.

================================================================================
HOW THESE WERE DERIVED — read this before trusting them
================================================================================
ORCHESTRATOR.md §5 requires an INDEPENDENT ORACLE: one session writes the engine,
a second session writes these expectations from the written rules alone, and
neither sees the other's work. **That protocol was NOT followed here.** This
session has no sub-session capability enabled, so the same author produced both.

The weaker substitute actually used: every expected DA and DQ below was
hand-derived from docs/04b §C03 and the bank shape in seeds/item_bank.py, and
written down, BEFORE app/modules/assessment/domain/ was implemented. The
arithmetic is shown in full so a clinician can check it on paper without reading
any code.

That is evidence, not verification. Agreement between an engine and expectations
by the same author is much weaker than agreement between two independent ones,
and neither substitutes for the clinician sign-off these gate.
                                                        → REVIEW-QUEUE.md #4
================================================================================

Bank shape (seeds/item_bank.py): 20 items per domain, ordinals 0-19,
bands [4,4,3,3,3,3], cumulative and month ranges:

    band 0: cum  4, months  0-12      band 3: cum 14, months 36-48
    band 1: cum  8, months 12-24      band 4: cum 17, months 48-60
    band 2: cum 11, months 24-36      band 5: cum 20, months 60-72

Rules: basal_consecutive=8, ceiling_consecutive=6, entry_band_offset=-1,
emerging_credit=0.50.

Scoring, per docs/04b §C03:
    raw = below_basal + passes + 0.50 x emerging      (capped at 20)
    DA  = linear interpolation of raw within its band
    DQ  = DA / chronological_months x 100
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from seeds.item_bank import build_bank, item_id

from app.modules.assessment.domain import engine
from app.modules.assessment.domain.state import Answer, Verdict

BANK = build_bank()


@dataclass(frozen=True)
class Golden:
    name: str
    domain: str
    child_months: float
    #: (ordinal, verdict) in administration order.
    answers: tuple[tuple[int, Verdict], ...]
    expected_raw: float
    expected_da: float
    expected_dq: float
    expected_dq_suppressed: bool = False
    expected_basal_ordinal: int | None = None
    expected_ceiling_ordinal: int | None = None
    hand_calculation: str = ""


Y = Verdict.YES
N = Verdict.NO
E = Verdict.EMERGING
NA = Verdict.NOT_APPLICABLE


GOLDEN_CASES: tuple[Golden, ...] = (
    # ---------------------------------------------------------------- 1 ----
    Golden(
        name="G1 language, typical profile with a clean ceiling",
        domain="language",
        child_months=42.00,
        answers=(
            # Down-walk from the entry band (band_of(42)=3, entry=3-1=2,
            # first ordinal of band 2 = 8).
            (8, Y),
            (7, Y),
            (6, Y),
            (5, Y),
            (4, Y),
            (3, Y),
            (2, Y),
            (1, Y),
            # Basal confirmed at ordinal 8 (run 1..8 = 8 consecutive yes).
            # Up-walk from 9.
            (9, Y),
            (10, Y),
            (11, Y),
            (12, N),
            (13, N),
            (14, N),
            (15, N),
            (16, N),
            (17, N),
        ),
        expected_raw=12.0,
        expected_da=40.00,
        expected_dq=95.2,
        expected_basal_ordinal=8,
        expected_ceiling_ordinal=17,
        hand_calculation="""
            Entry: band_of(42.00) = 3 (42 < 48). entry = 3 + (-1) = 2.
                   First ordinal of band 2 = 4+4 = 8.
            Basal: walking down 8,7,...,1 gives yes at ordinals 1-8, which is
                   8 consecutive = basal_consecutive. basal_ordinal = 8 (the
                   HIGHEST ordinal of the run). Ordinal 0 is never asked.
            Ceiling: up from 9. Yes at 9,10,11. No at 12,13,14,15,16,17 = 6
                   consecutive non-passes = ceiling_consecutive.
                   ceiling_ordinal = 17. Ordinals 18,19 scored no unasked.
            Scoring:
                   below_basal = 8            (ordinals 0-7 credited unasked)
                   passes at ordinal >= 8     = 8,9,10,11          = 4
                   emerging                                        = 0
                   raw = 8 + 4 + 0.50 x 0                          = 12
            DA:    raw 12 falls in band 3 (cum 11 < 12 <= cum 14).
                   span = 14 - 11 = 3;  frac = (12 - 11) / 3 = 0.333333
                   DA = 36 + 0.333333 x (48 - 36) = 36 + 4.00      = 40.00
            DQ:    40.00 / 42.00 x 100 = 95.238095...              = 95.2
        """,
    ),
    # ---------------------------------------------------------------- 2 ----
    Golden(
        name="G2 motor, bank floor reached without a basal",
        domain="motor",
        child_months=24.00,
        answers=(
            # band_of(24) = 2 (24 < 36). entry = 1. First ordinal of band 1 = 4.
            (4, Y),
            (3, Y),
            (2, Y),
            (1, Y),
            (0, Y),
            # Only 5 consecutive: the floor is hit before a basal forms.
            (5, Y),
            (6, Y),
            (7, Y),
            (8, Y),
            (9, N),
            (10, N),
            (11, N),
            (12, N),
            (13, N),
            (14, N),
        ),
        expected_raw=9.0,
        expected_da=28.00,
        expected_dq=116.7,
        expected_basal_ordinal=0,
        expected_ceiling_ordinal=14,
        hand_calculation="""
            Entry: band_of(24.00) = 2 (24 is NOT < 24, so not band 1).
                   entry = 2 + (-1) = 1. First ordinal of band 1 = 4.
            Basal: down-walk 4,3,2,1,0 = 5 consecutive yes, short of 8, and
                   ordinal 0 is the floor. Rule: 'bank floor reached without a
                   basal -> treat ordinal 0 as the basal'. basal_ordinal = 0,
                   basal_assumed = True. This is the case a clinician must see.
            Ceiling: up from 1, skipping 1-4 (already answered) to 5.
                   Yes at 5,6,7,8. No at 9..14 = 6 consecutive.
                   ceiling_ordinal = 14.
            Scoring:
                   below_basal = 0            (nothing is credited unasked)
                   passes at ordinal >= 0     = 0,1,2,3,4,5,6,7,8   = 9
                   raw = 0 + 9 + 0.50 x 0                           = 9
            DA:    raw 9 falls in band 2 (cum 8 < 9 <= cum 11).
                   span = 11 - 8 = 3;  frac = (9 - 8) / 3 = 0.333333
                   DA = 24 + 0.333333 x (36 - 24) = 24 + 4.00       = 28.00
            DQ:    28.00 / 24.00 x 100 = 116.666...                 = 116.7
        """,
    ),
    # ---------------------------------------------------------------- 3 ----
    Golden(
        name="G3 cognitive, emerging answers earning half credit",
        domain="cognitive",
        child_months=36.00,
        answers=(
            (8, Y),
            (7, Y),
            (6, Y),
            (5, Y),
            (4, Y),
            (3, Y),
            (2, Y),
            (1, Y),
            (9, Y),
            (10, E),
            (11, E),
            (12, N),
            (13, N),
            (14, E),
            (15, N),
        ),
        expected_raw=11.5,
        expected_da=38.00,
        expected_dq=105.6,
        expected_basal_ordinal=8,
        expected_ceiling_ordinal=15,
        hand_calculation="""
            Entry: band_of(36.00) = 3 (36 is NOT < 36). entry = 2 -> ordinal 8.
            Basal: as G1, basal_ordinal = 8.
            Ceiling: `emerging` is a NON-PASS for run purposes (docs/04b: the
                   conservative reading, so a run of 'sort of' answers cannot
                   inflate a ceiling). Up from 9:
                   9 yes -> run 0
                   10 em -> 1, 11 em -> 2, 12 no -> 3, 13 no -> 4,
                   14 em -> 5, 15 no -> 6  => ceiling_ordinal = 15.
            Scoring: emerging earns HALF credit even though it broke the run.
                   below_basal = 8
                   passes at ordinal >= 8     = 8, 9                = 2
                   emerging at ordinal >= 8   = 10, 11, 14          = 3
                   raw = 8 + 2 + 0.50 x 3 = 8 + 2 + 1.5             = 11.5
            DA:    raw 11.5 falls in band 3 (cum 11 < 11.5 <= cum 14).
                   span = 3;  frac = (11.5 - 11) / 3 = 0.166667
                   DA = 36 + 0.166667 x 12 = 36 + 2.00              = 38.00
            DQ:    38.00 / 36.00 x 100 = 105.5555...                = 105.6
        """,
    ),
    # ---------------------------------------------------------------- 4 ----
    Golden(
        name="G4 self-help, not_applicable excluded from runs and denominator",
        domain="self_help",
        child_months=60.00,
        answers=(
            # band_of(60) = 5 (60 is NOT < 60). entry = 4 -> first ordinal 14.
            (14, Y),
            (13, Y),
            (12, Y),
            (11, Y),
            (10, Y),
            (9, Y),
            (8, Y),
            (7, Y),
            (15, Y),
            (16, NA),
            (17, N),
            (18, N),
            (19, N),
        ),
        expected_raw=16.0,
        expected_da=56.00,
        expected_dq=93.3,
        expected_basal_ordinal=14,
        expected_ceiling_ordinal=None,
        hand_calculation="""
            Entry: band_of(60.00) = 5. entry = 4. First ordinal of band 4
                   = 4+4+3+3 = 14.
            Basal: down-walk 14..7 = 8 consecutive yes. basal_ordinal = 14.
            Ceiling: up from 15. 15 yes -> run 0. 16 not_applicable is INVISIBLE
                   to the run (neither extends nor breaks it). 17,18,19 no
                   -> run 1,2,3. Only 3 < 6, so NO ceiling is established; the
                   domain completes because ordinal 19 is the top of the bank.
            Scoring: not_applicable is excluded from the denominator entirely.
                   below_basal = 14
                   passes at ordinal >= 14    = 14, 15               = 2
                   not_applicable             = 16                   = 1
                   raw = 14 + 2 + 0.50 x 0                           = 16
            DA:    raw 16 falls in band 4 (cum 14 < 16 <= cum 17).
                   span = 17 - 14 = 3;  frac = (16 - 14) / 3 = 0.666667
                   DA = 48 + 0.666667 x (60 - 48) = 48 + 8.00        = 56.00
            DQ:    56.00 / 60.00 x 100 = 93.333...                   = 93.3
        """,
    ),
    # ---------------------------------------------------------------- 5 ----
    Golden(
        name="G5 socialisation, chronological age 0 suppresses DQ",
        domain="socialization",
        child_months=0.0,
        answers=(
            (0, Y),
            (1, Y),
            (2, N),
            (3, N),
            (4, N),
            (5, N),
            (6, N),
            (7, N),
        ),
        expected_raw=2.0,
        expected_da=6.00,
        expected_dq=0.0,
        expected_dq_suppressed=True,
        expected_basal_ordinal=0,
        expected_ceiling_ordinal=7,
        hand_calculation="""
            Entry: band_of(0.00) = 0. entry = max(0, 0 - 1) = 0 -> ordinal 0.
            Basal: the first answer IS ordinal 0, the floor, so the assumed-basal
                   rule fires immediately. basal_ordinal = 0, basal_assumed.
            Ceiling: up from 1. 1 yes -> run 0. 2..7 no = 6 consecutive.
                   ceiling_ordinal = 7.
            Scoring:
                   below_basal = 0
                   passes at ordinal >= 0     = 0, 1                 = 2
                   raw = 0 + 2 + 0.50 x 0                            = 2
            DA:    raw 2 falls in band 0 (2 <= cum 4).
                   span = 4 - 0 = 4;  frac = (2 - 0) / 4 = 0.50
                   DA = 0 + 0.50 x (12 - 0)                          = 6.00
            DQ:    DQ is DA / CA, and CA = 0. The ratio is UNDEFINED, not
                   infinite. DQ is suppressed and DA still reported.
        """,
    ),
    # ---------------------------------------------------------------- 6 ----
    Golden(
        name="G6 infant stimulation, child above the bank's range suppresses DQ",
        domain="infant_stim",
        child_months=90.00,
        answers=(
            (14, Y),
            (13, Y),
            (12, Y),
            (11, Y),
            (10, Y),
            (9, Y),
            (8, Y),
            (7, Y),
            (15, Y),
            (16, Y),
            (17, Y),
            (18, Y),
            (19, Y),
        ),
        expected_raw=20.0,
        expected_da=72.00,
        expected_dq=0.0,
        expected_dq_suppressed=True,
        expected_basal_ordinal=14,
        expected_ceiling_ordinal=None,
        hand_calculation="""
            Entry: 90 months exceeds every band's max (top band ends at 72), so
                   band_for_months clamps to the last band, 5. entry = 4
                   -> ordinal 14. out_of_range = 90 > 72 = True.
            Basal: down-walk 14..7 = 8 consecutive yes. basal_ordinal = 14.
            Ceiling: 15..19 all yes, so no ceiling. Completes at the bank top.
            Scoring:
                   below_basal = 14
                   passes at ordinal >= 14    = 14..19               = 6
                   raw = 14 + 6 = 20, capped at the 20-item domain = 20
            DA:    raw 20 falls in band 5 (cum 17 < 20 <= cum 20).
                   span = 20 - 17 = 3;  frac = (20 - 17) / 3 = 1.00
                   DA = 60 + 1.00 x (72 - 60)                        = 72.00
            DQ:    SUPPRESSED. The child is above what the bank measures, so a
                   quotient would compare them against the instrument's ceiling
                   rather than against themselves. DA still stands, but it is a
                   floor on ability, not a measurement of it.
        """,
    ),
)


def _replay(case: Golden) -> tuple[object, object]:
    answers = [
        Answer(item_id=item_id(case.domain, ordinal), verdict=verdict)
        for ordinal, verdict in case.answers
    ]
    state = engine.replay(bank=BANK, child_months=case.child_months, answers=answers)
    scores = engine.score(state, BANK)
    return state, scores


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda c: c.name)
def test_golden_developmental_age(case: Golden) -> None:
    _state, scores = _replay(case)
    score = scores[case.domain]  # type: ignore[index]
    assert score.raw == pytest.approx(case.expected_raw), case.hand_calculation
    assert score.developmental_age_months == pytest.approx(case.expected_da, abs=0.005), (
        case.hand_calculation
    )


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda c: c.name)
def test_golden_developmental_quotient(case: Golden) -> None:
    _state, scores = _replay(case)
    score = scores[case.domain]  # type: ignore[index]
    assert score.dq_suppressed is case.expected_dq_suppressed, case.hand_calculation
    assert score.developmental_quotient == pytest.approx(case.expected_dq, abs=0.05), (
        case.hand_calculation
    )


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda c: c.name)
def test_golden_basal_and_ceiling(case: Golden) -> None:
    state, _scores = _replay(case)
    domain_state = state.domains[case.domain]  # type: ignore[attr-defined]
    assert domain_state.basal_ordinal == case.expected_basal_ordinal, case.hand_calculation
    assert domain_state.ceiling_ordinal == case.expected_ceiling_ordinal, case.hand_calculation


def test_every_domain_has_exactly_one_golden_case() -> None:
    """One per domain, as P04 requires — no domain silently unverified."""
    assert {c.domain for c in GOLDEN_CASES} == set(BANK.domains)
    assert len(GOLDEN_CASES) == 6


def test_every_golden_case_shows_its_arithmetic() -> None:
    """A golden case without a visible hand calculation cannot be checked."""
    for case in GOLDEN_CASES:
        assert "raw =" in case.hand_calculation, case.name
        assert "DA" in case.hand_calculation, case.name
        assert "DQ" in case.hand_calculation, case.name
