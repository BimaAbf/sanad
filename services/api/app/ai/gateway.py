"""C15 — the single choke point for every model call.

**This is the only file in the project permitted to construct a provider
client.** `tools/guards/single_anthropic_client.py` fails the build if any other
module does, because every redaction pass, guardrail, budget check and audit row
lives on this path. A second client anywhere else is a route to the model that
bypasses all of them — including the redaction that keeps a child's name off the
wire.

With `AI_LIVE=0` (the default everywhere except a deliberate live test) this
makes **no network call at all** and replays recorded fixtures. That is not a
test convenience: it is how the whole product is built and verified before any
key exists.

Anthropic API rules, transcribed from the shared context block and NOT from
remembered patterns:
  * model id is exactly "claude-opus-5"
  * pass thinking={"type": "adaptive"}
  * do NOT pass temperature, top_p, top_k or budget_tokens - they return 400
  * no assistant-message prefill - it returns 400
  * structured output via output_config={"format": {"type": "json_schema", ...}}
  * effort tier via output_config={"effort": "low"|"medium"|"high"}
  * cache_control {"type": "ephemeral"} on the last stable block
  * always check response.stop_reason == "refusal" before reading content
  * client.beta.messages.create with betas=["server-side-fallback-2026-07-01"]
    and fallbacks="default"
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, TypeVar

import structlog
from pydantic import BaseModel, ValidationError

from app.ai.redaction import Pseudonymiser

logger = structlog.get_logger(__name__)

MODEL = "claude-opus-5"

T = TypeVar("T", bound=BaseModel)

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "ai"


class Outcome(StrEnum):
    OK = "ok"
    SCHEMA_ERROR = "schema_error"
    TIMEOUT = "timeout"
    REFUSAL = "refusal"
    BUDGET_EXCEEDED = "budget_exceeded"
    FLAG_OFF = "flag_off"
    NO_FIXTURE = "no_fixture"
    PROVIDER_ERROR = "provider_error"


#: docs/12 §2 routes per decision point. Effort is the cost/quality dial.
EFFORT_BY_DECISION: dict[str, str] = {
    "pgee_interpret": "high",
    "pgee_report": "high",
    "pgee_next_item": "low",
    "pgee_probe": "low",
    "tutor_plan": "low",
    "tutor_judge": "medium",
    "tutor_summary": "low",
    "safety_classify": "low",
}

MAX_TOKENS_BY_DECISION: dict[str, int] = {
    "pgee_interpret": 512,
    "pgee_report": 4096,
    "pgee_next_item": 256,
    "pgee_probe": 256,
    "tutor_plan": 512,
    "tutor_judge": 1024,
    "tutor_summary": 1024,
    "safety_classify": 256,
}


@dataclass(slots=True)
class LlmResult[T: BaseModel]:
    value: T | None
    outcome: Outcome
    call_id: str | None = None
    #: What was actually sent, post-redaction. Retained so a test can assert no
    #: identifier crossed the boundary.
    request_redacted: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, int] = field(default_factory=dict)
    latency_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.value is not None


def canonical_json(payload: Any) -> str:
    """sort_keys=True, ensure_ascii=False.

    Both matter. Stable key order is what makes the prompt prefix byte-identical
    across calls, which is what makes prompt caching hit. `ensure_ascii=False`
    keeps Arabic as Arabic instead of exploding every character into a \\uXXXX
    escape that would triple the token count.
    """
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def fixture_key(decision_point: str, payload: Mapping[str, Any]) -> str:
    """Content-addressed fixture name. Deterministic across runs and machines."""
    digest = hashlib.sha256(canonical_json(payload).encode()).hexdigest()[:16]
    return f"{decision_point}.{digest}"


def build_messages(
    *,
    system_frozen: Sequence[Mapping[str, Any]],
    few_shot_block: str,
    child_context: Mapping[str, Any],
    volatile: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Prompt layout, ordered for cache hits (docs/03 §3.2).

    Frozen system blocks first, then the frozen few-shot block, then semi-stable
    child context, then this turn's volatile payload. `cache_control` goes on the
    LAST stable block, so everything before it is a reusable prefix. Putting a
    volatile value anywhere above that line silently destroys the cache and
    multiplies the bill without failing a single test — which is exactly why
    `tools/guards/prompt_cache_hit.py` exists.
    """
    system: list[dict[str, Any]] = [dict(block) for block in system_frozen]
    if few_shot_block:
        system.append({"type": "text", "text": few_shot_block})
    if system:
        system[-1]["cache_control"] = {"type": "ephemeral"}

    user_content = canonical_json({"child": dict(child_context), "turn": dict(volatile)})
    messages = [{"role": "user", "content": user_content}]
    return system, messages


class FixtureStore:
    """Replays recorded provider responses. No network, ever."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or FIXTURE_ROOT
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def path_for(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def load(self, key: str) -> dict[str, Any] | None:
        path = self.path_for(key)
        if not path.exists():
            return None
        loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return loaded

    def record(self, key: str, payload: Mapping[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.path_for(key).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )


class LlmGateway:
    """Every model call in the product goes through `call_structured`."""

    def __init__(
        self,
        *,
        live: bool = False,
        fixtures: FixtureStore | None = None,
        budget_check: Any | None = None,
        flag_check: Any | None = None,
    ) -> None:
        self.live = live
        self.fixtures = fixtures or FixtureStore()
        self.budget_check = budget_check
        self.flag_check = flag_check
        #: Everything sent this process, for the PII assertion tests.
        self.sent_payloads: list[dict[str, Any]] = []

    async def call_structured(
        self,
        *,
        decision_point: str,
        schema_model: type[T],
        system_frozen: Sequence[Mapping[str, Any]] = (),
        few_shot_block: str = "",
        child_context: Mapping[str, Any] | None = None,
        volatile: Mapping[str, Any] | None = None,
        pseudonymiser: Pseudonymiser | None = None,
        child_id: str | None = None,
        correlation_id: str = "",
    ) -> LlmResult[T]:
        started = time.perf_counter()
        pseudo = pseudonymiser or Pseudonymiser()

        if self.flag_check is not None and not await self.flag_check(decision_point, child_id):
            return LlmResult(None, Outcome.FLAG_OFF)

        if self.budget_check is not None and not await self.budget_check(child_id):
            logger.info("ai_budget_exceeded", decision_point=decision_point)
            return LlmResult(None, Outcome.BUDGET_EXCEEDED)

        # Redaction happens BEFORE anything is serialised for sending, so there
        # is no window in which an unredacted payload exists on this path.
        payload_child = pseudo.scrub(dict(child_context or {}))
        payload_volatile = pseudo.scrub(dict(volatile or {}))

        system, messages = build_messages(
            system_frozen=system_frozen,
            few_shot_block=few_shot_block,
            child_context=payload_child,
            volatile=payload_volatile,
        )
        request = {
            "model": MODEL,
            "system": system,
            "messages": messages,
            "thinking": {"type": "adaptive"},
            "output_config": {
                "format": {
                    "type": "json_schema",
                    "schema": schema_model.model_json_schema(),
                },
                "effort": EFFORT_BY_DECISION.get(decision_point, "low"),
            },
            "max_tokens": MAX_TOKENS_BY_DECISION.get(decision_point, 512),
            "betas": ["server-side-fallback-2026-07-01"],
            "fallbacks": "default",
        }
        self.sent_payloads.append(request)

        key = fixture_key(decision_point, {"child": payload_child, "turn": payload_volatile})
        recorded = self.fixtures.load(key)

        if recorded is None:
            if not self.live:
                logger.info("ai_fixture_missing", decision_point=decision_point)
                return LlmResult(
                    None,
                    Outcome.NO_FIXTURE,
                    request_redacted=request,
                    latency_ms=_elapsed_ms(started),
                )
            recorded = await self._call_provider(request)

        # A refusal is checked BEFORE the content is read.
        if recorded.get("stop_reason") == "refusal":
            return LlmResult(
                None,
                Outcome.REFUSAL,
                request_redacted=request,
                usage=dict(recorded.get("usage", {})),
                latency_ms=_elapsed_ms(started),
            )

        try:
            value = schema_model.model_validate(recorded.get("content"))
        except ValidationError as exc:
            logger.info(
                "ai_schema_error",
                decision_point=decision_point,
                count=len(exc.errors()),
            )
            return LlmResult(
                None,
                Outcome.SCHEMA_ERROR,
                request_redacted=request,
                usage=dict(recorded.get("usage", {})),
                latency_ms=_elapsed_ms(started),
            )

        return LlmResult(
            value,
            Outcome.OK,
            call_id=recorded.get("id"),
            request_redacted=request,
            usage=dict(recorded.get("usage", {})),
            latency_ms=_elapsed_ms(started),
        )

    async def _call_provider(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """The live path. Unreachable without an explicit AI_LIVE=1 and a key.

        Deliberately raises rather than silently degrading: reaching here without
        a key is a configuration error, and pretending otherwise would make a
        test appear to pass against a model that was never called.
        """
        raise NotImplementedError(
            "Live provider calls are not wired up. The architecture runs on "
            "fixtures by design; see SETUP.md §2 for which gate needs a key."
        )


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
