"""The Groq request shape, and the LangChain adapter over the gateway.

docs/12 §2 routes every decision point to Groq. Everything here is about the
request that goes out and the envelope that comes back -- no network is
involved, because the point of the shapers being pure functions is that the
contract is testable without one.
"""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel, ConfigDict

from app.ai.gateway import (
    GROQ_MODEL,
    MODEL,
    LlmGateway,
    Outcome,
    Provider,
    anthropic_request,
    canonical_json,
    groq_request,
)
from app.ai.langchain import (
    GatewayCall,
    GatewayInput,
    GatewayRunnable,
    SyncNotSupportedError,
    frozen_system,
    unwrap,
)
from app.core.config import Settings


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: str


SYSTEM = [{"type": "text", "text": "RUBRIC"}, {"type": "text", "text": "SHAPE"}]
MESSAGES = [{"role": "user", "content": '{"a":1}'}]


def _groq() -> dict:
    return groq_request(
        decision_point="tutor_judge",
        schema_model=Verdict,
        system=SYSTEM,
        messages=MESSAGES,
    )


# --- the Groq request shape -------------------------------------------------


def test_groq_request_uses_the_documented_model_id() -> None:
    assert _groq()["model"] == GROQ_MODEL == "openai/gpt-oss-120b"


def test_groq_joins_every_system_block_rather_than_dropping_any() -> None:
    """Keeping only the first block would silently discard the rubric and the
    few-shot examples while still returning a plausible answer."""
    content = _groq()["messages"][0]["content"]
    assert "RUBRIC" in content
    assert "SHAPE" in content


def test_groq_sends_a_strict_json_schema() -> None:
    """Without `strict`, Groq treats the schema as a hint and a missing field
    comes back as a well-formed object that fails Pydantic -- reported as a
    model problem when it was a request-construction one."""
    schema = _groq()["response_format"]["json_schema"]
    assert schema["strict"] is True
    assert schema["schema"] == Verdict.model_json_schema()


def test_groq_is_greedy() -> None:
    """Every decision point here is closed-set; a sampled choice is a different
    choice some fraction of the time."""
    assert _groq()["temperature"] == 0


def test_groq_carries_no_anthropic_only_field() -> None:
    """`thinking`, `betas` and `cache_control` are 400s on this surface."""
    request = _groq()
    for field in ("thinking", "betas", "fallbacks", "output_config", "system"):
        assert field not in request
    assert "cache_control" not in json.dumps(request)


def test_anthropic_request_still_carries_its_required_fields() -> None:
    request = anthropic_request(
        decision_point="tutor_judge",
        schema_model=Verdict,
        system=SYSTEM,
        messages=MESSAGES,
    )
    assert request["model"] == MODEL
    assert request["thinking"] == {"type": "adaptive"}
    assert request["betas"] == ["server-side-fallback-2026-07-01"]
    # cache_control belongs on the LAST stable block, not the first.
    assert "cache_control" not in request["system"][0]


def test_canonical_json_keeps_arabic_as_arabic() -> None:
    """Escaping would roughly triple the token count of an Arabic prompt."""
    assert canonical_json({"label": "أحمر"}) == '{"label":"أحمر"}'


# --- provider selection -----------------------------------------------------


def test_gateway_defaults_to_groq() -> None:
    assert LlmGateway().provider is Provider.GROQ


def test_gateway_builds_the_request_for_its_provider() -> None:
    for provider, expected in ((Provider.GROQ, GROQ_MODEL), (Provider.ANTHROPIC, MODEL)):
        gateway = LlmGateway(provider=provider)
        import asyncio

        asyncio.run(
            gateway.call_structured(
                decision_point="tutor_judge",
                schema_model=Verdict,
                system_frozen=SYSTEM,
                volatile={"a": 1},
            )
        )
        assert gateway.sent_payloads[-1]["model"] == expected


# --- settings ---------------------------------------------------------------


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "database_url": "postgresql+asyncpg://u:p@localhost:5432/d",
        "redis_url": "redis://localhost:6379/0",
        "s3_endpoint_url": "http://localhost:9000",
        "s3_region": "us-east-1",
        "s3_bucket": "b",
        "s3_access_key_id": "k",
        "s3_secret_access_key": "s",
    }
    return Settings(**{**base, **overrides})  # type: ignore[arg-type]


def test_live_groq_without_a_groq_key_is_a_startup_failure() -> None:
    """Degrading to fixtures here would make a live smoke test pass without
    ever reaching a model."""
    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        _settings(ai_live=True, ai_provider="groq", groq_api_key=None)


def test_an_anthropic_key_does_not_satisfy_a_groq_deployment() -> None:
    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        _settings(ai_live=True, ai_provider="groq", anthropic_api_key="sk-ant-x")


def test_ai_api_key_returns_the_configured_providers_key() -> None:
    """The wrong provider's key here is a 401 from a correct deployment."""
    settings = _settings(ai_provider="groq", groq_api_key="gk", anthropic_api_key="ak")
    assert settings.ai_api_key == "gk"
    assert _settings(ai_provider="anthropic", anthropic_api_key="ak").ai_api_key == "ak"


def test_an_unknown_provider_is_rejected() -> None:
    with pytest.raises(ValueError, match="AI_PROVIDER"):
        _settings(ai_live=True, ai_provider="ollama", groq_api_key="gk")


def test_no_key_is_fine_while_ai_is_not_live() -> None:
    """The default configuration. Fixtures replay and no network call happens."""
    assert _settings().ai_live is False


# --- the LangChain adapter --------------------------------------------------


async def test_runnable_routes_through_the_gateway() -> None:
    gateway = LlmGateway()
    runnable = GatewayRunnable(
        gateway, GatewayCall("tutor_judge", Verdict, frozen_system("RUBRIC"))
    )
    result = await runnable.ainvoke(GatewayInput(volatile={"a": 1}))
    assert result.outcome is Outcome.NO_FIXTURE
    assert gateway.sent_payloads, "the request must still have been assembled"


def test_runnable_refuses_the_sync_path() -> None:
    """A sync bridge here would be a thread-pool deadlock waiting for a caller
    who does not know they created one."""
    runnable = GatewayRunnable(LlmGateway(), GatewayCall("tutor_judge", Verdict))
    with pytest.raises(SyncNotSupportedError):
        runnable.invoke(GatewayInput())


def test_unwrap_returns_none_for_every_non_ok_outcome() -> None:
    from app.ai.gateway import LlmResult

    for outcome in Outcome:
        if outcome is Outcome.OK:
            continue
        assert unwrap(LlmResult(None, outcome), decision_point="tutor_judge") is None
