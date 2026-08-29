"""LangChain bindings for the LLM gateway.

**Why this file exists rather than `langchain-groq`.** The obvious way to use
LangChain here is `ChatGroq`, and it is the wrong way. `ChatGroq` constructs its
own provider client, which means a chain built on it reaches the model without
passing through `LlmGateway.call_structured` -- and therefore without the
redaction that keeps a child's name off the wire, without the budget check,
without the flag check, without fixture replay, and without landing in
`sent_payloads` where the PII assertions read it.
`tools/guards/single_anthropic_client.py` would fail the build on it, and that
guard is right to.

So the dependency runs the other way: LangChain's `Runnable` and `BaseRetriever`
interfaces are implemented ON TOP of the gateway. Chains compose with `|` as
usual, `RunnableParallel`/`RunnableLambda` work as usual, LangGraph nodes await
these like any other runnable -- and every model call still goes through the one
choke point.

Async only, deliberately. `Runnable.invoke` is implemented as a refusal rather
than as `asyncio.run(...)`: the gateway is async all the way down, the API that
calls it is async, and a sync bridge here would be a thread-pool deadlock
waiting for a caller who does not know they created one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeVar

import structlog
from langchain_core.runnables import Runnable, RunnableConfig
from pydantic import BaseModel

from app.ai.gateway import LlmGateway, LlmResult, Outcome
from app.ai.redaction import Pseudonymiser

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


class SyncNotSupportedError(RuntimeError):
    """Raised by `invoke`. See the module docstring."""


@dataclass(frozen=True, slots=True)
class GatewayCall:
    """Everything about a decision point that does not change per request.

    Holding the frozen halves here rather than passing them per invocation is
    what keeps them byte-identical across calls. On Anthropic that is the
    prompt-cache prefix; on Groq there is no cache to hit (docs/12 SS1) but the
    stability still matters, because `fixture_key` is a hash of what was sent
    and a prefix that drifts turns every replay into a cache miss.
    """

    decision_point: str
    schema_model: type[BaseModel]
    system_frozen: tuple[Mapping[str, Any], ...] = ()
    few_shot_block: str = ""


@dataclass(frozen=True, slots=True)
class GatewayInput:
    """One invocation's variable half."""

    child_context: Mapping[str, Any] = field(default_factory=dict)
    volatile: Mapping[str, Any] = field(default_factory=dict)
    child_id: str | None = None
    correlation_id: str = ""
    pseudonymiser: Pseudonymiser | None = None


class GatewayRunnable(Runnable[GatewayInput, LlmResult[Any]]):
    """A LangChain `Runnable` whose only route to a model is the gateway.

    Returns the full `LlmResult` rather than the unwrapped value. That is not
    ceremony: `Outcome.NO_FIXTURE`, `BUDGET_EXCEEDED`, `REFUSAL` and
    `SCHEMA_ERROR` are all ordinary, expected states of this product, each with
    a different correct response, and a runnable that returned `None` for all
    four would erase the distinction at the one place a caller can still act on
    it. Every consumer in this codebase branches on `.outcome`.
    """

    def __init__(self, gateway: LlmGateway, call: GatewayCall) -> None:
        self._gateway = gateway
        self._call = call

    @property
    def InputType(self) -> type:  # noqa: N802 - LangChain's spelling
        return GatewayInput

    def invoke(
        self,
        input: GatewayInput,  # noqa: A002 - LangChain's parameter name
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> LlmResult[Any]:
        raise SyncNotSupportedError(
            f"{type(self).__name__} is async-only; await ainvoke() or use the "
            "async LangGraph/LCEL entry points."
        )

    async def ainvoke(
        self,
        input: GatewayInput,  # noqa: A002 - LangChain's parameter name
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> LlmResult[Any]:
        return await self._gateway.call_structured(
            decision_point=self._call.decision_point,
            schema_model=self._call.schema_model,
            system_frozen=self._call.system_frozen,
            few_shot_block=self._call.few_shot_block,
            child_context=input.child_context,
            volatile=input.volatile,
            pseudonymiser=input.pseudonymiser,
            child_id=input.child_id,
            correlation_id=input.correlation_id,
        )


def unwrap[M: BaseModel](result: LlmResult[M], *, decision_point: str) -> M | None:
    """The parsed value, or None with the reason logged.

    A helper rather than a runnable so that a caller who wants the distinction
    keeps it and a caller who does not is not forced to write the same four
    lines. The log line is the audit trail for a decision point that fell back.
    """
    if result.outcome is Outcome.OK:
        return result.value
    logger.info(
        "ai_fell_back",
        decision_point=decision_point,
        outcome=result.outcome.value,
        latency_ms=result.latency_ms,
    )
    return None


def system_block(text: str) -> dict[str, Any]:
    """One frozen system block, in the shape both request shapers accept."""
    return {"type": "text", "text": text}


def frozen_system(*texts: str) -> tuple[dict[str, Any], ...]:
    return tuple(system_block(text) for text in texts if text)


def render_documents(documents: Sequence[Any], *, limit: int = 12) -> list[dict[str, Any]]:
    """LangChain `Document`s as the plain JSON the gateway serialises.

    The gateway sends `canonical_json` of a mapping, so a `Document` object
    would arrive as its repr. Converting here -- rather than letting a chain
    author remember to -- is what keeps `page_content` out of the payload in a
    form the redaction pass cannot walk into.
    """
    rendered: list[dict[str, Any]] = []
    for document in documents[:limit]:
        metadata = dict(getattr(document, "metadata", {}) or {})
        rendered.append(
            {
                "kind": str(metadata.get("kind", "note")),
                "at": str(metadata.get("at", "")),
                "text": str(getattr(document, "page_content", "")),
            }
        )
    return rendered


__all__ = [
    "GatewayCall",
    "GatewayInput",
    "GatewayRunnable",
    "SyncNotSupportedError",
    "frozen_system",
    "render_documents",
    "system_block",
    "unwrap",
]
