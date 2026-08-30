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

TWO PROVIDERS, ONE CHOKE POINT. docs/12 routes every decision point to Groq
`openai/gpt-oss-120b`; the Anthropic path is retained because docs/12 SS2 leaves
DP1/DP4 open pending the `evals/datasets/interpret_ar.jsonl` measurement. Which
one answers is a config value, not a code path the caller can see -- both return
the same normalised {id, stop_reason, content, usage} shape, which is what lets
one fixture corpus stand in for either.

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

Groq rules (OpenAI-compatible surface at /chat/completions), spoken over plain
httpx rather than the Groq SDK for the same reason `voice/transport.py` does --
`tools/guards/single_anthropic_client.py` names `Groq`/`OpenAI` constructors as
violations everywhere, and this file is the one place a violation would be
allowed. Using httpx keeps even the permitted exception unused:
  * model id "openai/gpt-oss-120b"
  * system blocks collapse into ONE system message; there is no block list and
    no cache_control -- Groq has no prompt caching (docs/12 SS1), which is why the
    frozen prefix is a cost liability there rather than a saving
  * structured output via response_format={"type": "json_schema", "json_schema":
    {"name": ..., "schema": ..., "strict": true}}
  * temperature 0 -- unlike Anthropic this is accepted, and a sampled answer to
    a closed-set question is a different answer some fraction of the time
  * a refusal arrives as finish_reason "content_filter", normalised here to the
    same "refusal" stop_reason the Anthropic path produces
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

import structlog
from pydantic import BaseModel, ValidationError

from app.ai.redaction import Pseudonymiser

if TYPE_CHECKING:  # pragma: no cover - typing only
    from anthropic import AsyncAnthropic

logger = structlog.get_logger(__name__)

MODEL = "claude-opus-5"

#: docs/12 SS2 routes DP0, DP2, DP3 and DP4 here, and leaves DP1 open.
GROQ_MODEL = "openai/gpt-oss-120b"

T = TypeVar("T", bound=BaseModel)


class Provider(StrEnum):
    ANTHROPIC = "anthropic"
    GROQ = "groq"


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
    # Free prose read by a parent about their own child. The highest-stakes
    # prose in the product after the PGEE report, and routed accordingly.
    "caregiver_chat": "medium",
    # Picking one id from seven. docs/12 SS2: a small model does this fine.
    "child_chat": "low",
    # The teaching decision, taken once per activity while a child waits. It is
    # a choice from closed sets over a bounded evidence bundle, and the
    # deterministic fallback is a good decision rather than a broken one -- so
    # latency matters more here than an extra increment of quality.
    "tutor_brain": "low",
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
    "caregiver_chat": 700,
    # One phrase id and nothing else. A budget this small is itself a
    # constraint: there is no room to write a sentence to a child.
    "child_chat": 64,
    # Fourteen closed-set fields and up to eight short reason codes.
    "tutor_brain": 512,
}


#: Groq counts a reasoning model's hidden reasoning against
#: `max_completion_tokens`, and `openai/gpt-oss-120b` is a reasoning model.
#: MAX_TOKENS_BY_DECISION sizes the ANSWER -- 512 for a plan, 64 for one phrase
#: id -- so sending it as the completion cap meant the whole budget went on
#: reasoning and the model was cut off before it emitted a single byte of JSON.
#: Groq reports that as HTTP 400 `json_validate_failed` with
#: `"failed_generation": "max completion tokens reached before generating a
#: valid document"`, which this file maps to `Outcome.PROVIDER_ERROR` and every
#: caller absorbs as a deterministic fallback -- so the live AI path failed
#: silently, visible only as an AI-source rate of zero. Measured: a
#: `tutor_plan` call spends ~560 reasoning tokens before ~170 of answer.
#:
#: The answer stays bounded by its schema (`reason_ar` is max_length=240,
#: `phrase_id` max_length=40) rather than by the token cap, so the headroom
#: loosens no output contract.
REASONING_HEADROOM_BY_EFFORT: dict[str, int] = {
    "low": 1024,
    "medium": 2048,
    "high": 4096,
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


def anthropic_request(
    *,
    decision_point: str,
    schema_model: type[BaseModel],
    system: Sequence[Mapping[str, Any]],
    messages: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """The Anthropic Messages shape. Every field is in the module docstring."""
    return {
        "model": MODEL,
        "system": [dict(block) for block in system],
        "messages": [dict(message) for message in messages],
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


def strict_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """A Pydantic JSON Schema, rewritten to what `strict: true` will accept.

    Groq validates a `strict` json_schema the way OpenAI does, and it is
    stricter than JSON Schema itself: EVERY key in `properties` must appear in
    `required`, and every object must set `additionalProperties: false`. A
    Pydantic field with a default is simply absent from `required`, so
    `NextExercisePlan.grounded_in` and `CaregiverAnswer.used_document_ids` --
    both `default_factory=list` -- made every live request a 400:

        invalid JSON schema for response_format: 'tutor_plan': /required:
        `required` is required to be supplied and to be an array including
        every key in properties

    The gateway catches that as `Outcome.PROVIDER_ERROR` and every caller
    handles it by falling back to the deterministic path. Nothing raised, no
    test failed, and the AI half of the product was unreachable the moment
    `AI_LIVE=1` -- visible only as an AI-source rate of zero.

    Requiring an optional field costs nothing here: both are lists, the model
    can return `[]`, and Pydantic accepts an explicit empty list for a
    `default_factory` field. `extra="forbid"` on the models already implies
    `additionalProperties: false`, but it is set unconditionally so that a
    model declared without it cannot fail the same way.

    The walk covers `$defs`, because a nested model is emitted there and
    referenced by `$ref`, and a nested object left un-strict fails the same
    check.
    """
    rewritten: dict[str, Any] = {}
    for key, value in schema.items():
        if isinstance(value, Mapping):
            rewritten[key] = strict_schema(value)
        elif isinstance(value, list):
            rewritten[key] = [
                strict_schema(item) if isinstance(item, Mapping) else item for item in value
            ]
        else:
            rewritten[key] = value

    # `type == "object"`, not merely "has a `properties` key": the mapping UNDER
    # `properties` is walked by this same recursion, and a model with a field
    # actually named `properties` would otherwise have `required` and
    # `additionalProperties` injected into its field container.
    properties = rewritten.get("properties")
    if rewritten.get("type") == "object" and isinstance(properties, Mapping):
        rewritten["required"] = list(properties)
        rewritten["additionalProperties"] = False
    return rewritten


def groq_request(
    *,
    decision_point: str,
    schema_model: type[BaseModel],
    system: Sequence[Mapping[str, Any]],
    messages: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """The OpenAI-compatible chat shape Groq serves.

    The system blocks are joined with a blank line rather than sent as a list:
    Groq takes one system string, and dropping all but the first block -- the
    obvious alternative -- would silently discard the rubric and the few-shot
    examples while still returning a plausible answer. `cache_control` is
    dropped because there is nothing on the other side to honour it.

    `strict` is set on the schema. Without it Groq treats the schema as a hint
    and a missing required field comes back as a well-formed object that fails
    Pydantic validation -- reported as SCHEMA_ERROR, which reads as a model
    problem rather than a request-construction one.
    """
    joined = "\n\n".join(str(block.get("text", "")) for block in system if block.get("text"))
    chat: list[dict[str, Any]] = []
    if joined:
        chat.append({"role": "system", "content": joined})
    chat.extend({"role": m["role"], "content": m["content"]} for m in messages)
    return {
        "model": GROQ_MODEL,
        "messages": chat,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": decision_point,
                "schema": strict_schema(schema_model.model_json_schema()),
                "strict": True,
            },
        },
        # Greedy. A closed-set choice that is sampled is a different choice some
        # fraction of the time, and every decision point here is closed-set.
        "temperature": 0,
        # The same cost/quality dial the Anthropic path passes as
        # `output_config.effort`, spelled the way gpt-oss takes it, plus the
        # reasoning headroom that dial implies.
        "reasoning_effort": EFFORT_BY_DECISION.get(decision_point, "low"),
        "max_completion_tokens": (
            MAX_TOKENS_BY_DECISION.get(decision_point, 512)
            + REASONING_HEADROOM_BY_EFFORT[EFFORT_BY_DECISION.get(decision_point, "low")]
        ),
        "stream": False,
    }


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
        api_key: str | None = None,
        provider: Provider = Provider.GROQ,
        groq_base_url: str = "https://api.groq.com/openai/v1",
        fixtures: FixtureStore | None = None,
        budget_check: Any | None = None,
        flag_check: Any | None = None,
        record_live: bool | None = None,
        timeout_s: float = 60.0,
    ) -> None:
        self.live = live
        self.api_key = api_key
        #: docs/12 SS2 makes Groq the default for every decision point.
        self.provider = provider
        self.groq_base_url = groq_base_url.rstrip("/")
        self.fixtures = fixtures or FixtureStore()
        self.budget_check = budget_check
        self.flag_check = flag_check
        #: A live call with no fixture writes one, so the corpus this product is
        #: verified against is a by-product of running it rather than a file
        #: somebody has to remember to create. Off when replaying.
        self.record_live = live if record_live is None else record_live
        self.timeout_s = timeout_s
        #: Constructed once, on first live use. An AsyncAnthropic per call would
        #: open a new connection pool per call.
        self._client: AsyncAnthropic | None = None
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
        shape = groq_request if self.provider is Provider.GROQ else anthropic_request
        request = shape(
            decision_point=decision_point,
            schema_model=schema_model,
            system=system,
            messages=messages,
        )
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
            try:
                recorded = await self._call_provider(request)
            except TimeoutError:
                logger.info("ai_timeout", decision_point=decision_point)
                return LlmResult(
                    None,
                    Outcome.TIMEOUT,
                    request_redacted=request,
                    latency_ms=_elapsed_ms(started),
                )
            except Exception as exc:  # noqa: BLE001 -- see below
                # Deliberately blind. A provider failure is a normal state of
                # this product and the caller has a defined behaviour for it
                # (Outcome.PROVIDER_ERROR); narrowing this would mean naming
                # every exception type two SDKs and an HTTP client can raise,
                # and the one missed from that list becomes a 500 on a child's
                # session instead of a fallback.
                logger.info(
                    "ai_provider_error",
                    decision_point=decision_point,
                    exc_type=type(exc).__name__,
                )
                return LlmResult(
                    None,
                    Outcome.PROVIDER_ERROR,
                    request_redacted=request,
                    latency_ms=_elapsed_ms(started),
                )
            if self.record_live:
                self.fixtures.record(key, recorded)

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

    def _provider_client(self) -> AsyncAnthropic:
        """The one provider client in the product.

        `tools/guards/single_anthropic_client.py` fails the build if this
        constructor appears in any other module, because every redaction pass,
        guardrail and budget check lives on the path above it.

        Imported lazily so that the fixture path — which is every test and every
        run without a key — never pays for the SDK import.
        """
        if self._client is None:
            from anthropic import AsyncAnthropic

            if not self.api_key:
                # Reached only with live=True, which Settings already refuses
                # without a key. Kept because a caller can construct the gateway
                # directly, and a None key must not become an anonymous request.
                raise RuntimeError("live gateway constructed without an API key")
            self._client = AsyncAnthropic(api_key=self.api_key, timeout=self.timeout_s)
        return self._client

    async def _call_provider(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Dispatch to the configured provider. Both return the same shape."""
        if self.provider is Provider.GROQ:
            return await self._call_groq(request)
        return await self._call_anthropic(request)

    async def _call_groq(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """The Groq live path, over plain httpx.

        Normalises into the same {id, stop_reason, content, usage} envelope the
        Anthropic path returns, so a fixture recorded against either provider
        replays against the other. Three translations do the work:

        * `finish_reason: "content_filter"` becomes `stop_reason: "refusal"`,
          which is the state `call_structured` checks before reading content.
        * the assistant message's text is parsed as JSON here rather than by the
          caller, matching the Anthropic branch -- unparseable text becomes
          content=None, reported as SCHEMA_ERROR.
        * `usage` keys are passed through as ints; the names differ from
          Anthropic's and are not renamed, because a cost ledger that silently
          maps `completion_tokens` onto `output_tokens` would hide which
          provider a row came from.
        """
        import httpx

        if not self.api_key:
            raise RuntimeError("live gateway constructed without an API key")

        url = f"{self.groq_base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.post(url, headers=headers, json=dict(request))
        except httpx.TimeoutException as exc:
            raise TimeoutError(str(exc)) from exc
        response.raise_for_status()
        payload: dict[str, Any] = response.json()

        usage = {
            name: int(value)
            for name, value in (payload.get("usage") or {}).items()
            if isinstance(value, int)
        }
        choices = payload.get("choices") or []
        first = choices[0] if choices else {}

        if first.get("finish_reason") == "content_filter":
            return {
                "id": payload.get("id"),
                "stop_reason": "refusal",
                "content": None,
                "usage": usage,
            }

        text = ((first.get("message") or {}).get("content")) or None
        content: Any = None
        if text is not None:
            try:
                content = json.loads(text)
            except json.JSONDecodeError:
                logger.info("ai_unparseable_content", model=payload.get("model"))

        return {
            "id": payload.get("id"),
            "stop_reason": first.get("finish_reason"),
            "content": content,
            "usage": usage,
        }

    async def _call_anthropic(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """The live path. Unreachable without an explicit AI_LIVE=1 and a key.

        Returns the same shape a fixture carries — `id`, `stop_reason`,
        `content`, `usage` — so replay and live differ in exactly one thing:
        where the bytes came from. That is what lets a recorded fixture be a
        faithful stand-in rather than an approximation of one.

        The request is passed through as built. Every field in it is there for a
        documented reason (module docstring), and a client that re-derived any of
        them would be a second place where the API contract lives.
        """
        import anthropic

        client = self._provider_client()
        try:
            response = await client.beta.messages.create(**dict(request))
        except anthropic.APITimeoutError as exc:
            # Re-raised as the stdlib type so the caller maps it to
            # Outcome.TIMEOUT without importing the provider SDK.
            raise TimeoutError(str(exc)) from exc

        usage_model = getattr(response, "usage", None)
        usage = {
            name: int(value)
            for name, value in (usage_model.model_dump() if usage_model else {}).items()
            if isinstance(value, int)
        }

        # Checked by the caller before any content is read, but the refusal is
        # carried through rather than interpreted here.
        if response.stop_reason == "refusal":
            return {
                "id": response.id,
                "stop_reason": "refusal",
                "content": None,
                "usage": usage,
            }

        # output_config.format guarantees a text block holding valid JSON. A
        # missing or unparseable one is returned as content=None, which the
        # caller reports as SCHEMA_ERROR — the model answered, it just did not
        # answer in the shape that was asked for.
        text = next((b.text for b in response.content if b.type == "text"), None)
        content: Any = None
        if text is not None:
            try:
                content = json.loads(text)
            except json.JSONDecodeError:
                logger.info("ai_unparseable_content", model=response.model)

        return {
            "id": response.id,
            "stop_reason": response.stop_reason,
            "content": content,
            "usage": usage,
        }


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
