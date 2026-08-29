"""Property and edge-case tests for the assessment engine.

The P04 properties, verbatim:
  * replaying any legal answer sequence gives identical scores regardless of the
    order in which domains were interleaved
  * DA is monotonically non-decreasing in the number of `yes` answers
  * DQ is never negative; DQ > 200 sets a warning flag rather than being
    returned raw
  * correcting an answer and replaying equals administering the corrected
    sequence from scratch
"""

from __future__ import annotations

import time

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from seeds.item_bank import build_bank, item_id

from app.modules.assessment.domain import engine
from app.modules.assessment.domain.bands import age_equivalent, band_for_months, entry_band
from app.modules.assessment.domain.bank import Bank, BankItem
from app.modules.assessment.domain.basal_ceiling import find_basal, find_ceiling
from app.modules.assessment.domain.propagation import propagate
from app.modules.assessment.domain.scoring import DQ_WARNING_THRESHOLD, domain_score
from app.modules.assessment.domain.state import (
    Answer,
    Band,
    ItemRef,
    Rules,
    Verdict,
)

BANK = build_bank()
VERDICTS = [Verdict.YES, Verdict.EMERGING, Verdict.NO, Verdict.NOT_APPLICABLE, Verdict.SKIPPED]


# --- ordering independence --------------------------------------------------


@settings(max_examples=120, suppress_health_check=[HealthCheck.too_slow])
@given(
    seed=st.integers(min_value=0, max_value=10_000),
    verdicts=st.lists(st.sampled_from(VERDICTS), min_size=12, max_size=12),
)
def test_domain_interleaving_does_not_change_scores(seed: int, verdicts: list[Verdict]) -> None:
    """P04: identical scores regardless of how domains were interleaved.

    Two domains are answered with the same per-domain sequences; only the
    interleaving differs. Every score must match exactly.
    """
    left, right = "language", "motor"
    a = [Answer(item_id(left, i), v) for i, v in enumerate(verdicts[:6])]
    b = [Answer(item_id(right, i), v) for i, v in enumerate(verdicts[6:])]

    grouped = a + b
    interleaved: list[Answer] = []
    for i in range(6):
        # Deterministic but seed-varied interleaving.
        if (seed >> i) & 1:
            interleaved.extend([a[i], b[i]])
        else:
            interleaved.extend([b[i], a[i]])

    scores_grouped = engine.score(
        engine.replay(bank=BANK, child_months=36.0, answers=grouped), BANK
    )
    scores_interleaved = engine.score(
        engine.replay(bank=BANK, child_months=36.0, answers=interleaved), BANK
    )
    for code in (left, right):
        assert scores_grouped[code] == scores_interleaved[code]


# --- monotonicity in passes -------------------------------------------------


@settings(max_examples=100)
@given(passes=st.integers(min_value=0, max_value=19))
def test_da_is_non_decreasing_in_the_number_of_yes_answers(passes: int) -> None:
    """P04: DA is monotonically non-decreasing in the number of `yes` answers."""

    def da_for(count: int) -> float:
        answers = [
            Answer(item_id("language", i), Verdict.YES if i < count else Verdict.NO)
            for i in range(20)
        ]
        state = engine.replay(bank=BANK, child_months=48.0, answers=answers)
        return engine.score(state, BANK)["language"].developmental_age_months

    assert da_for(passes + 1) >= da_for(passes)


def test_da_is_non_decreasing_across_the_whole_range() -> None:
    """The same property swept exhaustively rather than sampled."""
    values = []
    for count in range(21):
        answers = [
            Answer(item_id("cognitive", i), Verdict.YES if i < count else Verdict.NO)
            for i in range(20)
        ]
        state = engine.replay(bank=BANK, child_months=48.0, answers=answers)
        values.append(engine.score(state, BANK)["cognitive"].developmental_age_months)
    assert values == sorted(values), values


# --- DQ bounds --------------------------------------------------------------


@settings(max_examples=200)
@given(
    child_months=st.floats(min_value=0.0, max_value=200.0, allow_nan=False),
    passes=st.integers(min_value=0, max_value=20),
)
def test_dq_is_never_negative_and_over_200_is_flagged(child_months: float, passes: int) -> None:
    """P04: DQ never negative; DQ > 200 sets a warning flag."""
    answers = [
        Answer(item_id("motor", i), Verdict.YES if i < passes else Verdict.NO) for i in range(20)
    ]
    state = engine.replay(bank=BANK, child_months=child_months, answers=answers)
    score = engine.score(state, BANK)["motor"]

    assert score.developmental_quotient >= 0.0
    assert score.developmental_age_months >= 0.0
    if score.dq_suppressed:
        assert score.developmental_quotient == 0.0
        assert not score.dq_warning
    elif score.developmental_quotient > DQ_WARNING_THRESHOLD:
        assert score.dq_warning, "a quotient above 200 must be flagged, not shipped raw"


def test_a_very_young_child_scoring_high_is_flagged_not_hidden() -> None:
    """A 6-month-old passing everything: DQ is huge and must carry a warning."""
    answers = [Answer(item_id("language", i), Verdict.YES) for i in range(20)]
    state = engine.replay(bank=BANK, child_months=6.0, answers=answers)
    score = engine.score(state, BANK)["language"]
    assert score.developmental_quotient > DQ_WARNING_THRESHOLD
    assert score.dq_warning
    assert not score.dq_suppressed


def test_dq_suppressed_at_exactly_zero_months() -> None:
    answers = [Answer(item_id("language", 0), Verdict.YES)]
    state = engine.replay(bank=BANK, child_months=0.0, answers=answers)
    assert engine.score(state, BANK)["language"].dq_suppressed


# --- correction equals replay ----------------------------------------------


@settings(max_examples=80, suppress_health_check=[HealthCheck.too_slow])
@given(
    verdicts=st.lists(st.sampled_from(VERDICTS), min_size=8, max_size=8),
    index=st.integers(min_value=0, max_value=7),
    corrected=st.sampled_from(VERDICTS),
)
def test_correcting_and_replaying_equals_administering_corrected_from_scratch(
    verdicts: list[Verdict], index: int, corrected: Verdict
) -> None:
    """P04: a correction replayed == the corrected sequence administered fresh.

    This is what makes append-only corrections safe. If it ever failed, an edit
    would silently produce a different developmental age than the same answers
    given in the first place.
    """
    original = [Answer(item_id("self_help", i), v) for i, v in enumerate(verdicts)]
    fixed = list(original)
    fixed[index] = Answer(item_id("self_help", index), corrected)

    from_correction = engine.score(engine.replay(bank=BANK, child_months=30.0, answers=fixed), BANK)
    from_scratch = engine.score(
        engine.replay(bank=BANK, child_months=30.0, answers=list(fixed)), BANK
    )
    assert from_correction == from_scratch


def test_a_correction_actually_changes_the_score() -> None:
    """Guard against the previous test passing vacuously."""
    answers = [Answer(item_id("self_help", i), Verdict.NO) for i in range(8)]
    before = engine.score(engine.replay(bank=BANK, child_months=30.0, answers=answers), BANK)[
        "self_help"
    ]
    answers[0] = Answer(item_id("self_help", 0), Verdict.YES)
    after = engine.score(engine.replay(bank=BANK, child_months=30.0, answers=answers), BANK)[
        "self_help"
    ]
    assert after.raw > before.raw


# --- replay determinism -----------------------------------------------------


@settings(max_examples=100)
@given(verdicts=st.lists(st.sampled_from(VERDICTS), min_size=1, max_size=20))
def test_replay_is_deterministic(verdicts: list[Verdict]) -> None:
    answers = [Answer(item_id("language", i), v) for i, v in enumerate(verdicts)]
    first = engine.score(engine.replay(bank=BANK, child_months=40.0, answers=answers), BANK)
    second = engine.score(engine.replay(bank=BANK, child_months=40.0, answers=answers), BANK)
    assert first == second


# --- band arithmetic --------------------------------------------------------


def test_age_equivalent_at_band_boundaries() -> None:
    cumulative = BANK.cumulative_by_band("language")
    assert age_equivalent(0, cumulative) == pytest.approx(0.0)
    assert age_equivalent(4, cumulative) == pytest.approx(12.0)
    assert age_equivalent(8, cumulative) == pytest.approx(24.0)
    assert age_equivalent(11, cumulative) == pytest.approx(36.0)
    assert age_equivalent(20, cumulative) == pytest.approx(72.0)
    # Beyond the bank: returns the top, never extrapolates.
    assert age_equivalent(25, cumulative) == pytest.approx(72.0)


def test_age_equivalent_with_no_bands_is_zero() -> None:
    assert age_equivalent(5, []) == 0.0


def test_age_equivalent_with_an_empty_band_carries_cumulative_forward() -> None:
    """A band with no items must not create a divide-by-zero or a jump."""
    cumulative = [(0, 4, 0, 12), (1, 4, 12, 24), (2, 8, 24, 36)]
    # raw 4 lands on band 0's boundary.
    assert age_equivalent(4, cumulative) == pytest.approx(12.0)
    # Band 1 is empty (span 0): frac is 0, so it reports the band floor.
    assert age_equivalent(4.0, cumulative) == pytest.approx(12.0)


@settings(max_examples=200)
@given(raw=st.floats(min_value=0.0, max_value=20.0, allow_nan=False))
def test_age_equivalent_is_non_decreasing_in_raw(raw: float) -> None:
    cumulative = BANK.cumulative_by_band("language")
    assert age_equivalent(raw + 0.5, cumulative) >= age_equivalent(raw, cumulative)


@pytest.mark.parametrize(
    ("months", "expected"),
    [(0, 0), (11.9, 0), (12, 1), (23.9, 1), (24, 2), (36, 3), (60, 5), (71.9, 5), (500, 5)],
)
def test_band_for_months(months: float, expected: int) -> None:
    assert band_for_months(BANK.bands, months) == expected


def test_band_for_months_needs_bands() -> None:
    with pytest.raises(ValueError, match="no bands"):
        band_for_months([], 12)


@pytest.mark.parametrize(
    ("months", "offset", "expected"),
    [(42, -1, 2), (0, -1, 0), (0, -3, 0), (90, -1, 4), (90, 0, 5), (12, -1, 0)],
)
def test_entry_band_is_clamped(months: float, offset: int, expected: int) -> None:
    assert entry_band(BANK.bands, months, offset) == expected


# --- run detection edge cases ----------------------------------------------


def test_skipped_breaks_a_basal_run_without_contributing() -> None:
    answered = {item_id("language", i): Verdict.YES for i in range(9)}
    answered[item_id("language", 4)] = Verdict.SKIPPED
    basal = find_basal(
        answered=answered,
        propagated=frozenset(),
        bank=BANK,
        domain="language",
        consecutive=8,
    )
    assert basal is None, "a skip in the middle must break the run"


def test_not_applicable_is_invisible_to_a_basal_run() -> None:
    answered = {item_id("language", i): Verdict.YES for i in range(9)}
    answered[item_id("language", 4)] = Verdict.NOT_APPLICABLE
    basal = find_basal(
        answered=answered,
        propagated=frozenset(),
        bank=BANK,
        domain="language",
        consecutive=8,
    )
    # 8 observed passes remain either side of the excluded item.
    assert basal == 8


def test_propagated_answers_do_not_establish_a_basal() -> None:
    """Propagated answers were never observed, so they cannot form a run."""
    answered = {item_id("language", i): Verdict.YES for i in range(9)}
    propagated = frozenset(item_id("language", i) for i in range(0, 9, 2))
    assert (
        find_basal(
            answered=answered,
            propagated=propagated,
            bank=BANK,
            domain="language",
            consecutive=8,
        )
        is None
    )


def test_skipped_cannot_close_a_ceiling() -> None:
    """A skip is not evidence of failure and must not end the assessment."""
    answered = {item_id("language", i): Verdict.NO for i in range(9, 16)}
    answered[item_id("language", 12)] = Verdict.SKIPPED
    ceiling = find_ceiling(
        answered=answered,
        propagated=frozenset(),
        bank=BANK,
        domain="language",
        consecutive=6,
        basal_ordinal=8,
    )
    assert ceiling is None


def test_a_failure_below_the_basal_cannot_close_a_ceiling() -> None:
    answered = {item_id("language", i): Verdict.NO for i in range(0, 8)}
    assert (
        find_ceiling(
            answered=answered,
            propagated=frozenset(),
            bank=BANK,
            domain="language",
            consecutive=6,
            basal_ordinal=8,
        )
        is None
    )


def test_emerging_counts_towards_a_ceiling() -> None:
    answered = {item_id("language", i): Verdict.EMERGING for i in range(9, 15)}
    ceiling = find_ceiling(
        answered=answered,
        propagated=frozenset(),
        bank=BANK,
        domain="language",
        consecutive=6,
        basal_ordinal=8,
    )
    assert ceiling == 14


def test_not_applicable_is_invisible_to_a_ceiling_run() -> None:
    answered = {item_id("language", i): Verdict.NO for i in range(9, 16)}
    answered[item_id("language", 12)] = Verdict.NOT_APPLICABLE
    ceiling = find_ceiling(
        answered=answered,
        propagated=frozenset(),
        bank=BANK,
        domain="language",
        consecutive=6,
        basal_ordinal=8,
    )
    assert ceiling == 15


def test_highest_qualifying_basal_wins() -> None:
    """With several qualifying runs the child gets the most advanced basal."""
    answered = {item_id("motor", i): Verdict.YES for i in range(12)}
    assert (
        find_basal(
            answered=answered,
            propagated=frozenset(),
            bank=BANK,
            domain="motor",
            consecutive=8,
        )
        == 11
    )


# --- propagation ------------------------------------------------------------


def test_propagation_credits_prerequisites_transitively() -> None:
    state = engine.initial_state(bank=BANK, child_months=40.0)
    ref = BANK.ref(item_id("language", 8))
    implied = propagate(state, ref, Verdict.YES, BANK)
    # implies_pass chains down by 2: 6 -> 4 -> 2 -> 0
    assert {r.ordinal for r, _ in implied} == {6, 4, 2, 0}
    assert all(v is Verdict.YES for _, v in implied)


@pytest.mark.parametrize(
    "verdict", [Verdict.NO, Verdict.EMERGING, Verdict.SKIPPED, Verdict.NOT_APPLICABLE]
)
def test_only_a_yes_propagates(verdict: Verdict) -> None:
    state = engine.initial_state(bank=BANK, child_months=40.0)
    ref = BANK.ref(item_id("language", 8))
    assert propagate(state, ref, verdict, BANK) == []


def test_propagation_never_overwrites_a_human_answer() -> None:
    answers = [Answer(item_id("language", 4), Verdict.NO)]
    state = engine.replay(bank=BANK, child_months=40.0, answers=answers)
    implied = propagate(state, BANK.ref(item_id("language", 8)), Verdict.YES, BANK)
    assert item_id("language", 4) not in {r.id for r, _ in implied}


def test_propagation_terminates_on_a_cyclic_bank() -> None:
    """A badly-authored bank with a cycle must not hang the engine."""
    bands = [Band(id=0, label="0-1", min_months=0, max_months=12)]
    items = [
        BankItem(
            ref=ItemRef(id="a", domain="d", band=0, sequence=1, ordinal=0),
            implies_pass=("b",),
        ),
        BankItem(
            ref=ItemRef(id="b", domain="d", band=0, sequence=2, ordinal=1),
            implies_pass=("a",),
        ),
    ]
    cyclic = Bank.build(version="cyc", bands=bands, items=items)
    state = engine.initial_state(bank=cyclic, child_months=6.0)
    implied = propagate(state, cyclic.ref("a"), Verdict.YES, cyclic)
    assert {r.id for r, _ in implied} == {"b"}


def test_propagation_ignores_ids_absent_from_the_bank() -> None:
    bands = [Band(id=0, label="0-1", min_months=0, max_months=12)]
    items = [
        BankItem(
            ref=ItemRef(id="a", domain="d", band=0, sequence=1, ordinal=0),
            implies_pass=("ghost",),
        )
    ]
    bank = Bank.build(version="g", bands=bands, items=items)
    state = engine.initial_state(bank=bank, child_months=6.0)
    assert propagate(state, bank.ref("a"), Verdict.YES, bank) == []


def test_apply_answer_records_implied_items_and_reduces_remaining() -> None:
    """P04: propagation on a `yes` reduces the remaining item count."""
    state = engine.initial_state(bank=BANK, child_months=40.0)
    before = engine.remaining_estimate(state, BANK)
    new_state, implied = engine.apply_answer(
        state, BANK.ref(item_id("language", 8)), Verdict.YES, BANK
    )
    after = engine.remaining_estimate(new_state, BANK)
    assert len(implied) == 4
    # 1 observed + 4 implied = 5 fewer items outstanding.
    assert before - after == 5


def test_propagation_does_not_affect_basal_detection() -> None:
    """P04: propagation never affects basal or ceiling detection."""
    state = engine.initial_state(bank=BANK, child_months=40.0)
    new_state, implied = engine.apply_answer(
        state, BANK.ref(item_id("language", 8)), Verdict.YES, BANK
    )
    assert len(implied) == 4
    # Five passes exist but only one was observed, so no basal can form.
    assert new_state.domains["language"].basal_ordinal is None


# --- bank validation --------------------------------------------------------


def test_bank_rejects_non_dense_ordinals() -> None:
    bands = [Band(id=0, label="0-1", min_months=0, max_months=12)]
    items = [
        BankItem(ref=ItemRef(id="a", domain="d", band=0, sequence=1, ordinal=0)),
        BankItem(ref=ItemRef(id="c", domain="d", band=0, sequence=3, ordinal=2)),
    ]
    with pytest.raises(ValueError, match="non-dense ordinals"):
        Bank.build(version="bad", bands=bands, items=items)


def test_bank_lookups_outside_the_range_return_none() -> None:
    assert BANK.at("language", -1) is None
    assert BANK.at("language", 20) is None
    assert BANK.at("nosuchdomain", 0) is None
    assert BANK.count("nosuchdomain") == 0
    assert not BANK.has("nope")
    assert BANK.implies_pass("nope") == ()
    assert BANK.cumulative_by_band("nosuchdomain")[-1][1] == 0


def test_domain_with_no_items_in_the_entry_band_falls_back() -> None:
    """docs/04b failure mode: fall back to the nearest band with items."""
    bands = [Band(id=b, label=f"{b}", min_months=b * 12, max_months=(b + 1) * 12) for b in range(6)]
    items = [
        BankItem(ref=ItemRef(id=f"x{i}", domain="d", band=5, sequence=i + 1, ordinal=i))
        for i in range(3)
    ]
    sparse = Bank.build(version="sparse", bands=bands, items=items)
    state = engine.initial_state(bank=sparse, child_months=6.0)
    # Entry band would be 0; the only items are in band 5.
    assert state.domains["d"].entry_ordinal == 0


# --- completion and performance --------------------------------------------


def test_replay_skips_items_absent_from_the_bank() -> None:
    answers = [
        Answer(item_id("language", 0), Verdict.YES),
        Answer("does-not-exist", Verdict.YES),
    ]
    state = engine.replay(bank=BANK, child_months=40.0, answers=answers)
    assert len(state.domains["language"].answered) == 1


def test_mark_complete_finishes_every_domain() -> None:
    state = engine.initial_state(bank=BANK, child_months=40.0)
    assert not all(d.complete for d in state.domains.values())
    assert all(d.complete for d in engine.mark_complete(state).domains.values())


def test_candidates_returns_at_most_one_item_per_domain() -> None:
    state = engine.initial_state(bank=BANK, child_months=40.0)
    refs = engine.candidates(state, BANK, limit=10)
    assert len(refs) == len(BANK.domains)
    assert len({r.domain for r in refs}) == len(refs)


def test_candidates_prefers_the_current_domain_first() -> None:
    state = engine.initial_state(bank=BANK, child_months=40.0)
    refs = engine.candidates(state, BANK, limit=6, current_domain="motor")
    assert refs[0].domain == "motor"


def test_candidates_respects_the_limit() -> None:
    state = engine.initial_state(bank=BANK, child_months=40.0)
    assert len(engine.candidates(state, BANK, limit=2)) == 2


def test_candidates_excludes_completed_domains() -> None:
    answers = [Answer(item_id("language", i), Verdict.NO) for i in range(20)]
    state = engine.replay(bank=BANK, child_months=40.0, answers=answers)
    assert "language" not in {r.domain for r in engine.candidates(state, BANK, limit=10)}


def test_a_full_assessment_completes_within_the_time_budget() -> None:
    """P04: a synthetic 42-month child completes in < 200 ms of engine time."""
    state = engine.initial_state(bank=BANK, child_months=42.0)
    started = time.perf_counter()
    administered = 0
    while administered < 400:
        refs = engine.candidates(state, BANK, limit=1)
        if not refs:
            break
        ref = refs[0]
        # A plausible profile: passes up to the child's level, then failures.
        verdict = Verdict.YES if ref.ordinal <= 11 else Verdict.NO
        state, _ = engine.apply_answer(state, ref, verdict, BANK)
        administered += 1
    elapsed_ms = (time.perf_counter() - started) * 1000
    engine.score(state, BANK)

    assert engine_is_complete(state), "the assessment never terminated"
    assert elapsed_ms < 200, f"engine took {elapsed_ms:.1f} ms"


def engine_is_complete(state: object) -> bool:
    from app.modules.assessment.domain.basal_ceiling import is_complete

    return is_complete(state)  # type: ignore[arg-type]


def test_remaining_estimate_never_goes_negative() -> None:
    answers = [Answer(item_id(d, i), Verdict.NO) for d in BANK.domains for i in range(20)]
    state = engine.replay(bank=BANK, child_months=40.0, answers=answers)
    assert engine.remaining_estimate(state, BANK) == 0


def test_scoring_caps_raw_at_the_domain_item_count() -> None:
    """below_basal + passes can exceed the bank; the cap is what stops it."""
    answers = [Answer(item_id("language", i), Verdict.YES) for i in range(20)]
    state = engine.replay(bank=BANK, child_months=40.0, answers=answers)
    assert engine.score(state, BANK)["language"].raw == 20.0


def test_delta_is_reported_against_a_previous_assessment() -> None:
    answers = [
        Answer(item_id("language", i), Verdict.YES if i < 12 else Verdict.NO) for i in range(20)
    ]
    state = engine.replay(bank=BANK, child_months=42.0, answers=answers)
    scores = engine.score(state, BANK, previous={"language": 30.0})
    assert scores["language"].delta_da_months == pytest.approx(
        scores["language"].developmental_age_months - 30.0, abs=0.01
    )
    assert scores["motor"].delta_da_months is None


def test_domain_score_ignores_answers_for_items_outside_the_bank() -> None:
    state = engine.replay(
        bank=BANK,
        child_months=40.0,
        answers=[Answer(item_id("language", 0), Verdict.YES)],
    )
    domain_state = state.domains["language"]
    stale = {**domain_state.answered, "ghost-item": Verdict.YES}
    from dataclasses import replace

    score = domain_score(replace(domain_state, answered=stale), BANK, Rules(), 40.0)
    assert score.passes == 1


# --- remaining branch coverage on domain/ ----------------------------------
# The 100%-branch gate on app/modules/assessment/domain/ is a hard requirement
# (P04). These close the last few paths: each is a real edge case, not a
# coverage-chasing no-op.


def test_next_ordinal_up_returns_none_at_the_top_of_the_bank() -> None:
    """Every ordinal answered: the up-walk has nowhere left to go."""
    from dataclasses import replace

    from app.modules.assessment.domain.basal_ceiling import next_item, next_ordinal_up

    answers = [Answer(item_id("language", i), Verdict.YES) for i in range(20)]
    state = engine.replay(bank=BANK, child_months=40.0, answers=answers)
    domain_state = replace(state.domains["language"], complete=False, cursor_up=0)
    assert next_ordinal_up(domain_state, BANK) is None
    # next_item propagates that None rather than raising.
    assert next_item(domain_state, BANK) is None


def test_next_item_returns_none_for_a_completed_domain() -> None:
    from dataclasses import replace

    from app.modules.assessment.domain.basal_ceiling import next_item

    state = engine.initial_state(bank=BANK, child_months=40.0)
    done = replace(state.domains["language"], complete=True)
    assert next_item(done, BANK) is None


def test_next_candidates_skips_a_domain_with_no_state() -> None:
    """A bank domain absent from the state must be skipped, not crash."""
    from dataclasses import replace

    from app.modules.assessment.domain.basal_ceiling import next_candidates

    state = engine.initial_state(bank=BANK, child_months=40.0)
    partial = replace(state, domains={k: v for k, v in state.domains.items() if k != "language"})
    refs = next_candidates(partial, BANK, limit=10)
    assert "language" not in {r.domain for r in refs}
    assert len(refs) == len(BANK.domains) - 1


def test_bank_domain_of_resolves_an_item_to_its_domain() -> None:
    assert BANK.domain_of(item_id("motor", 3)) == "motor"


def test_first_ordinal_in_an_empty_domain_is_zero() -> None:
    """A domain declared with no items must not break state construction."""
    from app.modules.assessment.domain.engine import _first_ordinal_in_band

    assert _first_ordinal_in_band(BANK, "nosuchdomain", 2) == 0


def test_next_candidates_skips_a_domain_that_is_exhausted_but_not_flagged() -> None:
    """An incomplete domain with nothing left to ask contributes no candidate.

    `record()` normally marks such a domain complete, so this state is only
    reachable by construction — but a resumed checkpoint written by an older
    engine version could carry it, and it must not produce a phantom candidate.
    """
    from dataclasses import replace

    from app.modules.assessment.domain.basal_ceiling import next_candidates

    answers = [Answer(item_id("language", i), Verdict.YES) for i in range(20)]
    state = engine.replay(bank=BANK, child_months=40.0, answers=answers)
    exhausted = replace(state.domains["language"], complete=False, cursor_up=0)
    stuck = replace(state, domains={**state.domains, "language": exhausted})

    refs = next_candidates(stuck, BANK, limit=10)
    assert "language" not in {r.domain for r in refs}
