#!/usr/bin/env python
"""GUARD 2 — exactly one place may construct an Anthropic client.

Why this matters more than it looks: every guardrail, every redaction pass,
every budget check and every Langfuse span lives in app/ai/gateway.py. A second
`Anthropic()` constructed anywhere else is a path to the model that bypasses all
of them — including the redaction that keeps a child's name off the wire.

This guard is FULLY IMPLEMENTED now, not stubbed: it must be live before P03
writes the first client, or the first violation will already be in the tree.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from _common import APP_ROOT, GuardResult, python_files

#: The single file permitted to construct a provider client.
GATEWAY = APP_ROOT / "ai" / "gateway.py"

#: Constructor names that open a direct path to a model provider.
CLIENT_CONSTRUCTORS = frozenset(
    {
        "Anthropic",
        "AsyncAnthropic",
        "AnthropicBedrock",
        "AsyncAnthropicBedrock",
        "AnthropicVertex",
        "AsyncAnthropicVertex",
        "Groq",
        "AsyncGroq",
        "OpenAI",
        "AsyncOpenAI",
    }
)


def _constructor_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def check(app_root: Path = APP_ROOT, gateway: Path = GATEWAY) -> GuardResult:
    result = GuardResult("single-anthropic-client")
    if not app_root.exists():
        result.skip(f"{app_root} does not exist yet")
        return result

    for path in python_files(app_root):
        if path.resolve() == gateway.resolve():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            result.violation(path, exc.lineno or 0, f"could not parse: {exc.msg}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = _constructor_name(node)
                if name in CLIENT_CONSTRUCTORS:
                    result.violation(
                        path,
                        node.lineno,
                        f"constructs {name}() outside app/ai/gateway.py — every model "
                        f"call must go through the gateway so redaction, guardrails and "
                        f"budget checks cannot be bypassed",
                    )
    return result


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    sys.exit(check().report())
