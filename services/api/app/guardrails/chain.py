"""The guardrail chain and the per-decision-point layer registry.

`REQUIRED_LAYERS` is read by `tools/guards/required_guardrail_layer.py`, which
fails the build if a decision point that produces prose lacks
`ClinicalSafetyLayer`, or one that selects from a set lacks `CandidateSetLayer`.
That guard is why this table is data rather than scattered call sites.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from app.guardrails.layers import (
    GuardrailBlock,
    GuardrailEvent,
    GuardrailRejection,
    Outcome,
)


class SchemaLayer:
    """L2 — output matched the Pydantic model with extra='forbid'."""


class CandidateSetLayer:
    """L3 — the chosen id is a member of the engine's candidate set."""


class ClosedEnumLayer:
    """L3 — the verdict is a member of the closed enum."""


class ProbeAllowlistLayer:
    """L3 — the probe id is one of the item's approved templates."""


class NumericEqualityLayer:
    """L4 — every digit in the narrative equals an engine-computed value."""


class ClinicalSafetyLayer:
    """L5 — no diagnosis, prognosis, medication, deficit framing or false hope."""


class ConservatismLayer:
    """L6 — the AI verdict may equal or lower the deterministic one, never raise it."""


class ReadingLevelLayer:
    """Caregiver copy stays in plain register."""


class PiiLeakLayer:
    """Nothing from the children table appears in an outgoing payload."""


class RedFlagLayer:
    """Red-flag input bypasses the AI entirely and goes to a human."""


#: decision point -> the layers it MUST run. Keys are ai_decision_point enum
#: values from docs/02 §2. tools/guards/required_guardrail_layer.py enforces it.
REQUIRED_LAYERS: dict[str, list[type]] = {
    "pgee_next_item": [SchemaLayer, CandidateSetLayer],
    "pgee_interpret": [SchemaLayer, ClosedEnumLayer, RedFlagLayer],
    "pgee_probe": [SchemaLayer, ProbeAllowlistLayer, ClinicalSafetyLayer],
    "pgee_report": [
        SchemaLayer,
        ClinicalSafetyLayer,
        NumericEqualityLayer,
        ReadingLevelLayer,
        PiiLeakLayer,
    ],
    "tutor_plan": [SchemaLayer, CandidateSetLayer],
    # The per-activity teaching decision. CandidateSetLayer because it selects
    # the next skill from a set the deterministic engine built -- the AI may
    # reorder and choose, never add -- and ClosedEnumLayer because strategy,
    # modality, support level and activity type are all closed sets whose
    # members the child app has components for. A value outside them is a blank
    # screen, so it is repaired rather than rendered.
    "tutor_brain": [SchemaLayer, CandidateSetLayer, ClosedEnumLayer],
    "tutor_judge": [SchemaLayer, ClosedEnumLayer, ConservatismLayer],
    "tutor_summary": [SchemaLayer, ClinicalSafetyLayer, ReadingLevelLayer],
    "safety_classify": [SchemaLayer, ClinicalSafetyLayer],
    # The caregiver assistant writes prose a parent reads about their own child,
    # so it carries the same three layers as the PGEE report minus numeric
    # fidelity -- there are no engine-computed numbers in a chat answer to check
    # it against, and NumericEqualityLayer with an empty number set would pass
    # everything while looking like a guard.
    "caregiver_chat": [
        SchemaLayer,
        ClinicalSafetyLayer,
        ReadingLevelLayer,
        PiiLeakLayer,
        RedFlagLayer,
    ],
    # The child surface generates nothing: it selects one id from CHILD_PHRASES.
    # CandidateSetLayer is what makes "Nour can only say a reviewed phrase" true
    # rather than aspirational.
    "child_chat": [SchemaLayer, ClosedEnumLayer, CandidateSetLayer, RedFlagLayer],
}


@dataclass(slots=True)
class ChainResult:
    """What the chain concluded, and everything it recorded on the way."""

    value: Any
    outcome: Outcome
    events: list[GuardrailEvent]

    @property
    def ok(self) -> bool:
        return self.outcome in (Outcome.PASS, Outcome.REPAIRED)

    @property
    def blocked(self) -> bool:
        return self.outcome is Outcome.BLOCKED_ESCALATED


#: One validation step: raises GuardrailRejection/GuardrailBlock, or returns.
Check = Callable[[Any], None]


class GuardrailChain:
    """Run checks in order, stopping at the first failure.

    Order matters. Cheap deterministic checks run before expensive ones, and the
    safety block runs before anything that would ship the text — a rejection is
    recoverable, a block is not.
    """

    def __init__(self, decision_point: str, checks: Sequence[tuple[str, Check]]) -> None:
        self.decision_point = decision_point
        self.checks = list(checks)

    def run(self, value: Any) -> ChainResult:
        events: list[GuardrailEvent] = []
        for name, check in self.checks:
            try:
                check(value)
            except GuardrailBlock as block:
                events.append(block.as_event())
                return ChainResult(None, Outcome.BLOCKED_ESCALATED, events)
            except GuardrailRejection as rejection:
                events.append(rejection.as_event())
                return ChainResult(None, Outcome.REJECTED_FALLBACK, events)
            events.append(GuardrailEvent(name, Outcome.PASS))
        return ChainResult(value, Outcome.PASS, events)


def missing_layers(decision_point: str, declared: Sequence[type]) -> list[str]:
    """Which required layers a decision point has not declared."""
    required = REQUIRED_LAYERS.get(decision_point, [])
    declared_names = {layer.__name__ for layer in declared}
    return sorted(layer.__name__ for layer in required if layer.__name__ not in declared_names)
