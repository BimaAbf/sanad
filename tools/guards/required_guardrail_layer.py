#!/usr/bin/env python
"""GUARD 4 — every AI decision point declares the guardrail layers it needs.

Two invariants from docs/03:
  * a decision point that produces PROSE a human reads must run
    ClinicalSafetyLayer;
  * a decision point that SELECTS from a candidate set must run
    CandidateSetLayer, which is what makes "the AI may reorder, never add" true.

Forgetting one is invisible: the feature works, and the safety property is
simply absent.

STATUS: fully implemented, currently SKIPping because app/guardrails/ has no
        chain registration yet. TODO(P03): register the layers, then TODO(P05)
        and TODO(P08): confirm this reports PASS as each decision point lands.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from _common import APP_ROOT, GuardResult, python_files

GUARDRAILS_ROOT = APP_ROOT / "guardrails"

#: decision point -> layers it must declare. Keys are ai_decision_point enum
#: values from docs/02 §2. Transcribed from docs/03; a decision point absent
#: from this table is itself a violation once the registry exists.
REQUIRED_LAYERS: dict[str, frozenset[str]] = {
    "pgee_next_item": frozenset({"CandidateSetLayer"}),
    "pgee_interpret": frozenset({"ClosedEnumLayer"}),
    "pgee_probe": frozenset({"ClinicalSafetyLayer"}),
    "pgee_report": frozenset({"ClinicalSafetyLayer", "NumericEqualityLayer"}),
    "tutor_plan": frozenset({"CandidateSetLayer"}),
    "tutor_judge": frozenset({"ClosedEnumLayer"}),
    "tutor_summary": frozenset({"ClinicalSafetyLayer"}),
    "safety_classify": frozenset({"ClinicalSafetyLayer"}),
}


def _registry_source() -> list[Path]:
    return [p for p in python_files(GUARDRAILS_ROOT) if p.name == "chain.py"]


def check() -> GuardResult:
    result = GuardResult("required-guardrail-layer")
    sources = _registry_source()
    if not sources:
        result.skip("app/guardrails/chain.py does not exist yet — activates with P03")
        return result

    declared: dict[str, set[str]] = {}
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            # Looking for a mapping literal: {"pgee_report": [ClinicalSafetyLayer, ...]}
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values, strict=True):
                if not (isinstance(key, ast.Constant) and key.value in REQUIRED_LAYERS):
                    continue
                names: set[str] = set()
                for inner in ast.walk(value):
                    if isinstance(inner, ast.Name):
                        names.add(inner.id)
                    elif isinstance(inner, ast.Attribute):
                        names.add(inner.attr)
                declared.setdefault(str(key.value), set()).update(names)

    if not declared:
        result.skip("no decision-point layer registry found in chain.py yet")
        return result

    for decision_point, required in REQUIRED_LAYERS.items():
        if decision_point not in declared:
            result.violation(
                sources[0], 1, f"decision point {decision_point!r} is not registered"
            )
            continue
        missing = required - declared[decision_point]
        if missing:
            result.violation(
                sources[0],
                1,
                f"decision point {decision_point!r} is missing {sorted(missing)}",
            )
    return result


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    sys.exit(check().report())
