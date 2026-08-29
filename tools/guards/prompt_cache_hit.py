#!/usr/bin/env python
"""GUARD 3 — prompt caching is actually working.

The cost model in docs/12 assumes cache hits on the stable prompt prefix. A
refactor that moves the cache_control breakpoint does not fail a test; it just
multiplies the bill, silently, in production.

The assertion is: a recorded double call reports cache_read_input_tokens > 0 on
the second call.

This has two halves, and only one of them can be checked without a key:

  STRUCTURAL (live now) — the cache_control breakpoint must sit on the LAST
      system block, with nothing volatile above it. This is the regression that
      actually happens: someone moves a per-turn value into the system prompt,
      every request misses the cache, and no test fails.

  EMPIRICAL (still pending) — a recorded double call must report
      cache_read_input_tokens > 0. That needs a REAL recorded pair against a
      real provider, so it cannot be produced without ANTHROPIC_API_KEY. It is
      deliberately NOT faked: a fabricated fixture would assert that caching
      works when nobody has ever observed it working.
      TODO(Gate 4): record tests/evals/fixtures/prompt_cache_double_call.json
      from a real pair. The guard activates with no code change.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from _common import API_ROOT, GuardResult

FIXTURE = API_ROOT / "tests" / "evals" / "fixtures" / "prompt_cache_double_call.json"


def check_structure(result: GuardResult) -> None:
    """The breakpoint must be on the last system block. Checkable without a key."""
    try:
        sys.path.insert(0, str(API_ROOT))
        from app.ai.gateway import build_messages
    except ImportError:
        return

    system, messages = build_messages(
        system_frozen=[{"type": "text", "text": "frozen-rules"}],
        few_shot_block="frozen-examples",
        child_context={"age_months": 42},
        volatile={"turn": "volatile-value"},
    )
    gateway_file = API_ROOT / "app" / "ai" / "gateway.py"

    if not system:
        result.violation(gateway_file, 1, "no system blocks were produced")
        return
    if "cache_control" not in system[-1]:
        result.violation(
            gateway_file, 1, "the last system block carries no cache_control breakpoint"
        )
    for index, block in enumerate(system[:-1]):
        if "cache_control" in block:
            result.violation(
                gateway_file,
                1,
                f"system block {index} carries cache_control; the breakpoint must be "
                f"on the LAST stable block or the prefix above it is not reusable",
            )
    rendered = json.dumps(system, ensure_ascii=False)
    if "volatile-value" in rendered:
        result.violation(
            gateway_file,
            1,
            "a per-turn value appears in the cached system prefix — every request "
            "will miss the cache and the docs/12 cost model no longer holds",
        )
    if "volatile-value" not in json.dumps(messages, ensure_ascii=False):
        result.violation(gateway_file, 1, "the volatile turn never reached the message")


def check(fixture: Path = FIXTURE) -> GuardResult:
    result = GuardResult("prompt-cache-hit")
    check_structure(result)
    if result.violations:
        return result

    if not fixture.exists():
        result.skip(
            "structural check PASSED; the empirical half needs a real recorded "
            "double call (ANTHROPIC_API_KEY, Gate 4) — deliberately not faked"
        )
        return result

    payload = json.loads(fixture.read_text(encoding="utf-8"))
    calls = payload.get("calls", [])
    if len(calls) < 2:
        result.violation(fixture, 1, "fixture must record at least two calls")
        return result

    second = calls[1].get("usage", {})
    cache_read = second.get("cache_read_input_tokens", 0)
    if not isinstance(cache_read, int) or cache_read <= 0:
        result.violation(
            fixture,
            1,
            f"second call reported cache_read_input_tokens={cache_read!r}; the "
            f"cache_control breakpoint is not being hit and the cost model in "
            f"docs/12 no longer holds",
        )
    return result


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    sys.exit(check().report())
