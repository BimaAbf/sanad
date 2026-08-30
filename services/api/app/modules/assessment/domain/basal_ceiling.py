"""Basal and ceiling detection, and the administration state machine.

The rules, from docs/04b §C03:

* **Basal** — walk DOWN from the entry band until `basal_consecutive`
  consecutive `yes` answers exist. Everything below a confirmed basal is
  credited without being asked.
* **Ceiling** — then walk UP until `ceiling_consecutive` consecutive non-`yes`
  answers exist. Everything above is scored `no` without being asked.
* `emerging` is a non-pass for run purposes but earns partial credit in scoring.
* `not_applicable` is invisible to both runs.
* `skipped` breaks a run without contributing to it — the run restarts.
* Propagated answers were never observed, so they are excluded from run
  detection entirely, while still counting in scoring.

ONE CLARIFICATION OF THE SPEC, recorded in docs/adr/006-scoring-rules.md:
`basal_ordinal` is the **highest** ordinal of the confirmed run (which is what
makes the doc's `cursor_up = basal + 1` correct), and scoring credits ordinals
strictly *below* it as passes while counting answered items at or above it
normally. Read any other way, the doc's `raw = below_basal + yes_count + ...`
double-counts every item inside the basal run.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from app.modules.assessment.domain.bank import Bank
from app.modules.assessment.domain.state import (
    BREAKS_RUN,
    EXCLUDED_FROM_RUNS,
    PASSING,
    AssessmentState,
    DomainState,
    ItemRef,
    Verdict,
)


def _observed(answered: Mapping[str, Verdict], propagated: frozenset[str], item_id: str) -> bool:
    """Did a human actually answer this, as opposed to it being inferred?"""
    return item_id in answered and item_id not in propagated


def find_basal(
    *,
    answered: Mapping[str, Verdict],
    propagated: frozenset[str],
    bank: Bank,
    domain: str,
    consecutive: int,
) -> int | None:
    """The highest ordinal ending a run of `consecutive` observed passes.

    Scans downward from the top so that, when several runs qualify, the highest
    wins — the child gets the benefit of the most advanced basal established.
    """
    items = bank.items_in(domain)
    best: int | None = None
    run = 0
    for item in items:
        item_id = item.ref.id
        if not _observed(answered, propagated, item_id):
            run = 0
            continue
        verdict = answered[item_id]
        if verdict in EXCLUDED_FROM_RUNS:
            # Invisible: neither extends nor breaks the run.
            continue
        if verdict in PASSING:
            run += 1
            if run >= consecutive:
                best = item.ref.ordinal
        else:
            # Both an explicit non-pass and a `skipped` restart the run.
            run = 0
    return best


def find_ceiling(
    *,
    answered: Mapping[str, Verdict],
    propagated: frozenset[str],
    bank: Bank,
    domain: str,
    consecutive: int,
    basal_ordinal: int,
) -> int | None:
    """The highest ordinal of the first run of `consecutive` observed non-passes.

    Only looks above the basal: a failure below the basal is inside territory
    the child has already demonstrated, and must not close the assessment.
    """
    run = 0
    for item in bank.items_in(domain):
        if item.ref.ordinal <= basal_ordinal:
            continue
        item_id = item.ref.id
        if not _observed(answered, propagated, item_id):
            run = 0
            continue
        verdict = answered[item_id]
        if verdict in EXCLUDED_FROM_RUNS:
            continue
        if verdict in PASSING:
            run = 0
        elif verdict in BREAKS_RUN:
            # A skip is not evidence of failure, so it cannot help close a
            # ceiling. It restarts the run.
            run = 0
        else:
            run += 1
            if run >= consecutive:
                return item.ref.ordinal
    return None


def next_ordinal_down(domain_state: DomainState, bank: Bank) -> int | None:
    """The next unanswered ordinal at or below the down-cursor."""
    ordinal = domain_state.cursor_down
    while ordinal >= 0:
        ref = bank.at(domain_state.domain, ordinal)
        if ref is not None and ref.id not in domain_state.answered:
            return ordinal
        ordinal -= 1
    return None


def next_ordinal_up(domain_state: DomainState, bank: Bank) -> int | None:
    """The next unanswered ordinal at or above the up-cursor.

    Skipping already-answered ordinals matters: after a floor-assumed basal the
    cursor starts at 1 with ordinals 1..4 already answered from the down-walk.
    """
    ordinal = domain_state.cursor_up
    top = bank.max_ordinal(domain_state.domain)
    while ordinal <= top:
        ref = bank.at(domain_state.domain, ordinal)
        if ref is not None and ref.id not in domain_state.answered:
            return ordinal
        ordinal += 1
    return None


def next_item(domain_state: DomainState, bank: Bank) -> ItemRef | None:
    """The single item this domain would ask next, or None if it is finished."""
    if domain_state.complete:
        return None
    if domain_state.basal_ordinal is None:
        ordinal = next_ordinal_down(domain_state, bank)
    else:
        ordinal = next_ordinal_up(domain_state, bank)
    if ordinal is None:
        return None
    return bank.at(domain_state.domain, ordinal)


def next_candidates(
    state: AssessmentState, bank: Bank, limit: int = 5, current_domain: str | None = None
) -> list[ItemRef]:
    """Every item legal to ask right now, at most one per domain.

    Interleaved across domains so a caregiver is never asked twenty motor
    questions in a row, but with the current domain first so the AI ranker can
    prefer continuity (it may reorder this list; it may never add to it).
    """
    refs: list[ItemRef] = []
    for code in bank.domains:
        domain_state = state.domains.get(code)
        if domain_state is None or domain_state.complete:
            continue
        ref = next_item(domain_state, bank)
        if ref is not None:
            refs.append(ref)
    if current_domain is not None:
        refs.sort(key=lambda r: (r.domain != current_domain, r.domain, r.ordinal))
    return refs[:limit]


def record(
    state: AssessmentState,
    item: ItemRef,
    verdict: Verdict,
    bank: Bank,
    *,
    propagated: frozenset[str] = frozenset(),
) -> AssessmentState:
    """Apply one answer and return the new state. Never mutates."""
    domain_state = state.domains[item.domain]
    answered = {**domain_state.answered, item.id: verdict}
    rules = state.rules

    if domain_state.basal_ordinal is None:
        basal = find_basal(
            answered=answered,
            propagated=propagated,
            bank=bank,
            domain=item.domain,
            consecutive=rules.basal_consecutive,
        )
        if basal is not None:
            domain_state = replace(
                domain_state,
                answered=answered,
                basal_ordinal=basal,
                cursor_up=basal + 1,
            )
        elif item.ordinal == 0 and item.id not in propagated:
            # Bank floor reached with no basal run. Treat ordinal 0 as the
            # basal so the assessment can proceed, and flag it: a child who
            # never established a basal is exactly the case a clinician needs
            # to see rather than have smoothed over.
            #
            # `item.id not in propagated` is load-bearing. Evidence propagation
            # can reach ordinal 0 without anyone having been asked about it; if
            # that were allowed to assume a basal, a single `yes` high in the
            # bank would end the down-walk and silently change the score.
            domain_state = replace(
                domain_state,
                answered=answered,
                basal_ordinal=0,
                basal_assumed=True,
                cursor_up=1,
            )
        elif item.id in propagated:
            # A propagated answer moves no cursor: it was never asked, so it
            # tells us nothing about where to ask next.
            domain_state = replace(domain_state, answered=answered)
        else:
            domain_state = replace(domain_state, answered=answered, cursor_down=item.ordinal - 1)
    else:
        ceiling = find_ceiling(
            answered=answered,
            propagated=propagated,
            bank=bank,
            domain=item.domain,
            consecutive=rules.ceiling_consecutive,
            basal_ordinal=domain_state.basal_ordinal,
        )
        domain_state = replace(
            domain_state,
            answered=answered,
            cursor_up=item.ordinal + 1,
            ceiling_ordinal=ceiling,
            complete=ceiling is not None or item.ordinal >= bank.max_ordinal(item.domain),
        )

    # A domain with nothing left to ask is finished even without a ceiling.
    if not domain_state.complete and next_item(domain_state, bank) is None:
        domain_state = replace(domain_state, complete=True)

    return replace(state, domains={**state.domains, item.domain: domain_state})


def is_complete(state: AssessmentState) -> bool:
    return all(d.complete for d in state.domains.values())
