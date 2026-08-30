"""Developmental age, developmental quotient, and deltas.

Every number a caregiver sees about their child's development is computed here.
There is no AI anywhere in this file and there never will be: the LLM may narrate
these figures, it may never produce one.

Three suppression rules, each because the alternative would be actively harmful:

* **CA = 0** — DQ is a ratio to chronological age. At zero it is undefined, not
  infinite. DA is still reported.
* **Out of range** — if the child's age is beyond what the bank measures, the
  quotient is comparing against a ceiling rather than against the child. DQ is
  suppressed; DA still stands.
* **DQ > 200** — almost always a data-entry error rather than a real finding.
  The value is returned with `dq_warning` set rather than presented as fact.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.modules.assessment.domain.bands import age_equivalent
from app.modules.assessment.domain.bank import Bank
from app.modules.assessment.domain.state import (
    AssessmentState,
    DomainScore,
    DomainState,
    Rules,
    Verdict,
)

#: Above this, a quotient is flagged rather than trusted.
DQ_WARNING_THRESHOLD = 200.0


def _counts(
    domain_state: DomainState, bank: Bank, at_or_above: int
) -> tuple[int, int, int, int, int]:
    """(passes, emerging, fails, not_applicable, administered) at or above an ordinal.

    Restricted to ordinals at or above the basal because everything below it is
    already credited wholesale by `below_basal`. Counting both would credit each
    item inside the basal run twice.
    """
    passes = emerging = fails = not_applicable = administered = 0
    for item_id, verdict in domain_state.answered.items():
        if not bank.has(item_id):
            continue
        if bank.ref(item_id).ordinal < at_or_above:
            continue
        administered += 1
        if verdict is Verdict.YES:
            passes += 1
        elif verdict is Verdict.EMERGING:
            emerging += 1
        elif verdict is Verdict.NOT_APPLICABLE:
            not_applicable += 1
            administered -= 1  # excluded from the denominator entirely
        elif verdict is Verdict.SKIPPED:
            administered -= 1  # not observed, so not administered
        else:
            fails += 1
    return passes, emerging, fails, not_applicable, administered


def domain_score(
    domain_state: DomainState,
    bank: Bank,
    rules: Rules,
    child_months: float,
    *,
    out_of_range: bool = False,
    previous_da: float | None = None,
) -> DomainScore:
    below_basal = domain_state.basal_ordinal or 0
    passes, emerging, fails, not_applicable, administered = _counts(domain_state, bank, below_basal)

    raw = below_basal + passes + rules.emerging_credit * emerging
    raw = min(raw, float(bank.count(domain_state.domain)))

    da_months = age_equivalent(raw, bank.cumulative_by_band(domain_state.domain))

    dq_suppressed = child_months <= 0 or out_of_range
    dq = 0.0 if dq_suppressed else (da_months / child_months * 100)
    dq_warning = not dq_suppressed and dq > DQ_WARNING_THRESHOLD

    basal_band = None
    if domain_state.basal_ordinal is not None:
        ref = bank.at(domain_state.domain, domain_state.basal_ordinal)
        basal_band = ref.band if ref else None
    ceiling_band = None
    if domain_state.ceiling_ordinal is not None:
        ref = bank.at(domain_state.domain, domain_state.ceiling_ordinal)
        ceiling_band = ref.band if ref else None

    return DomainScore(
        domain=domain_state.domain,
        items_administered=administered,
        passes=passes,
        emerging=emerging,
        fails=fails,
        not_applicable=not_applicable,
        basal_band=basal_band,
        ceiling_band=ceiling_band,
        raw=round(raw, 4),
        developmental_age_months=round(da_months, 2),
        developmental_quotient=round(dq, 1),
        dq_suppressed=dq_suppressed,
        dq_warning=dq_warning,
        delta_da_months=(None if previous_da is None else round(da_months - previous_da, 2)),
    )


def score_all(
    state: AssessmentState,
    bank: Bank,
    *,
    previous: Mapping[str, float] | None = None,
) -> dict[str, DomainScore]:
    previous = previous or {}
    return {
        code: domain_score(
            domain_state,
            bank,
            state.rules,
            state.child_months,
            out_of_range=state.out_of_range,
            previous_da=previous.get(code),
        )
        for code, domain_state in state.domains.items()
    }
