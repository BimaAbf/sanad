"""The replay engine — the single entry point the service layer uses.

Corrections never mutate: a corrected answer is a new row, the old one is marked
superseded, and the whole assessment is replayed from the surviving sequence.
Replay is the only way to keep basal and ceiling consistent after an edit, and it
is cheap (well under 5 ms for 600 items).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace

from app.modules.assessment.domain.bands import entry_band
from app.modules.assessment.domain.bank import Bank
from app.modules.assessment.domain.basal_ceiling import next_candidates, record
from app.modules.assessment.domain.propagation import propagate
from app.modules.assessment.domain.scoring import score_all
from app.modules.assessment.domain.state import (
    Answer,
    AssessmentState,
    DomainScore,
    DomainState,
    ItemRef,
    Rules,
    Verdict,
    domain_states,
)


def initial_state(
    *, bank: Bank, child_months: float, rules: Rules | None = None
) -> AssessmentState:
    """Build the starting state for a child.

    `child_months` is the CORRECTED age (docs/04a §C02): entry bands use
    corrected, the report displays both.
    """
    rules = rules or Rules()
    entry: dict[str, tuple[int, int]] = {}
    for code in bank.domains:
        band_id = entry_band(bank.bands, child_months, rules.entry_band_offset)
        ordinal = _first_ordinal_in_band(bank, code, band_id)
        entry[code] = (band_id, ordinal)
    return AssessmentState(
        child_months=child_months,
        bank_version=bank.version,
        rules=rules,
        domains=domain_states(bank.domains, entry),
        out_of_range=child_months > bank.max_months,
    )


def _first_ordinal_in_band(bank: Bank, domain: str, band_id: int) -> int:
    """First ordinal in a band, falling back to the nearest band with items.

    A domain with no items in the entry band is a bank-authoring gap, not a
    child-facing error: fall back to the nearest populated band and carry on
    (docs/04b §C03 failure modes).
    """
    items = bank.items_in(domain)
    if not items:
        return 0
    exact = [i for i in items if i.ref.band == band_id]
    if exact:
        return exact[0].ref.ordinal
    nearest = min(items, key=lambda i: (abs(i.ref.band - band_id), i.ref.ordinal))
    return nearest.ref.ordinal


def apply_answer(
    state: AssessmentState,
    item: ItemRef,
    verdict: Verdict,
    bank: Bank,
    *,
    propagated: frozenset[str] = frozenset(),
) -> tuple[AssessmentState, list[tuple[ItemRef, Verdict]]]:
    """Record one observed answer plus everything it implies.

    Returns the new state and the implied answers, so the caller can persist
    them with source `evidence_propagated`.
    """
    new_state = record(state, item, verdict, bank, propagated=propagated)
    implied = propagate(new_state, item, verdict, bank)
    for ref, implied_verdict in implied:
        new_state = record(
            new_state,
            ref,
            implied_verdict,
            bank,
            propagated=propagated | {r.id for r, _ in implied},
        )
    return new_state, implied


def replay(
    *,
    bank: Bank,
    child_months: float,
    answers: Sequence[Answer],
    rules: Rules | None = None,
) -> AssessmentState:
    """Rebuild state from an answer sequence. Deterministic and total.

    An answer naming an item the bank does not contain is skipped rather than
    raising: a bank version can gain items, and an old assessment must still
    replay. `bank_version` is pinned on the assessment precisely so this is rare.
    """
    state = initial_state(bank=bank, child_months=child_months, rules=rules)
    propagated = frozenset(a.item_id for a in answers if a.propagated)
    for answer in answers:
        if not bank.has(answer.item_id):
            continue
        state = record(state, bank.ref(answer.item_id), answer.verdict, bank, propagated=propagated)
    return state


def score(
    state: AssessmentState, bank: Bank, *, previous: Mapping[str, float] | None = None
) -> dict[str, DomainScore]:
    return score_all(state, bank, previous=previous)


def candidates(
    state: AssessmentState,
    bank: Bank,
    *,
    limit: int = 5,
    current_domain: str | None = None,
) -> list[ItemRef]:
    return next_candidates(state, bank, limit=limit, current_domain=current_domain)


def remaining_estimate(state: AssessmentState, bank: Bank) -> int:
    """How many items are still unanswered in incomplete domains.

    Used for the progress range, which may only ever narrow.
    """
    total = 0
    for code, domain_state in state.domains.items():
        if domain_state.complete:
            continue
        total += bank.count(code) - len(domain_state.answered)
    return max(total, 0)


def mark_complete(state: AssessmentState) -> AssessmentState:
    """Force every domain complete — used when a caregiver finalises early."""
    return replace(
        state,
        domains={code: _complete(domain_state) for code, domain_state in state.domains.items()},
    )


def _complete(domain_state: DomainState) -> DomainState:
    return replace(domain_state, complete=True)
