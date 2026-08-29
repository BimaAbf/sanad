"""Evidence propagation: a `yes` on a higher-order skill implies its prerequisites.

This removes 15-25% of items from a typical session, which is the difference
between a caregiver finishing and a caregiver giving up at item 40.

Propagated answers are:
  * written with source `evidence_propagated`,
  * **excluded** from basal and ceiling run detection — they were never observed,
  * **counted** in scoring,
  * shown on the review screen with a one-tap "actually, no" correction.

The traversal is iterative with a `seen` set, so a cyclic `implies_pass` graph in
a badly-authored bank terminates instead of hanging.
"""

from __future__ import annotations

from app.modules.assessment.domain.bank import Bank
from app.modules.assessment.domain.state import AssessmentState, ItemRef, Verdict


def propagate(
    state: AssessmentState, item: ItemRef, verdict: Verdict, bank: Bank
) -> list[tuple[ItemRef, Verdict]]:
    """Items implied by this answer, transitively. Only a `yes` propagates.

    An `emerging` deliberately does not: partial performance of a skill is not
    evidence that its prerequisites are fully mastered, and crediting them would
    inflate the developmental age.
    """
    if verdict is not Verdict.YES:
        return []

    implied: list[tuple[ItemRef, Verdict]] = []
    seen = {item.id}
    stack = list(bank.implies_pass(item.id))

    while stack:
        item_id = stack.pop()
        if item_id in seen or not bank.has(item_id):
            continue
        seen.add(item_id)
        ref = bank.ref(item_id)
        domain_state = state.domains.get(ref.domain)
        # Never overwrite an answer a human actually gave.
        if domain_state is not None and item_id in domain_state.answered:
            continue
        implied.append((ref, Verdict.YES))
        stack.extend(bank.implies_pass(item_id))

    return implied
