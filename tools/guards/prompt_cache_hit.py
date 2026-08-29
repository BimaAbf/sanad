#!/usr/bin/env python
"""GUARD 3 — prompt caching is actually working.

The cost model in docs/12 assumes cache hits on the stable prompt prefix. A
refactor that moves the cache_control breakpoint does not fail a test; it just
multiplies the bill, silently, in production.

The assertion is: a recorded double call reports cache_read_input_tokens > 0 on
the second call.

STATUS: SKIPs until the recorded fixture exists. It cannot be implemented before
        P03 produces the gateway that records it.
        TODO(P03): write tests/evals/fixtures/prompt_cache_double_call.json from
        a real recorded pair, then this guard activates with no code change.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from _common import API_ROOT, GuardResult

FIXTURE = API_ROOT / "tests" / "evals" / "fixtures" / "prompt_cache_double_call.json"


def check(fixture: Path = FIXTURE) -> GuardResult:
    result = GuardResult("prompt-cache-hit")
    if not fixture.exists():
        result.skip(f"{fixture.relative_to(API_ROOT.parents[1])} not recorded yet — activates with P03")
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
