"""Integration tests against the docker-compose stack.

These exercise the engine/session/redis lifecycle, which unit tests cannot
reach without mocking exactly the thing that is worth testing. Marked
`integration`; CI runs them with real postgres and redis services.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.config import Settings, get_settings
from app.core.db import (
    check_database,
    dispose_engine,
    get_engine,
    get_session,
    init_engine,
)
from app.core.redis import check_redis, dispose_redis, get_redis, init_redis
from app.core.storage import check_storage
from app.main import create_app

pytestmark = pytest.mark.integration


@pytest.fixture
def settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
async def _stack(settings: Settings):  # type: ignore[no-untyped-def]
    init_engine(settings)
    init_redis(settings)
    yield
    await dispose_engine()
    await dispose_redis()


async def test_engine_is_reused(settings: Settings, _stack: None) -> None:
    assert init_engine(settings) is get_engine()


async def test_get_session_yields_a_working_session(_stack: None) -> None:
    agen = get_session()
    session = await anext(agen)
    result = await session.execute(text("SELECT 42"))
    assert result.scalar_one() == 42
    with pytest.raises(StopAsyncIteration):
        await anext(agen)


async def test_get_session_rolls_back_on_exception(_stack: None) -> None:
    agen = get_session()
    session = await anext(agen)
    await session.execute(text("SELECT 1"))
    with pytest.raises(RuntimeError):
        await agen.athrow(RuntimeError("boom"))
    assert not session.in_transaction()


async def test_probes_report_ok_against_the_real_stack(settings: Settings, _stack: None) -> None:
    assert (await check_database())["status"] == "ok"
    assert (await check_redis())["status"] == "ok"
    assert (await check_storage(settings))["status"] == "ok"


async def test_probes_report_error_without_raising(settings: Settings) -> None:
    """A probe must never propagate — a dead dependency is a 503, not a 500."""
    await dispose_engine()
    await dispose_redis()
    assert (await check_database())["status"] == "error"
    assert (await check_redis())["status"] == "error"
    broken = settings.model_copy(update={"s3_endpoint_url": "http://127.0.0.1:1"})
    assert (await check_storage(broken))["status"] == "error"


async def test_redis_client_is_reused(settings: Settings, _stack: None) -> None:
    assert init_redis(settings) is get_redis()
    await get_redis().set("misk:test", "1", ex=5)
    assert await get_redis().get("misk:test") == "1"


async def test_uninitialised_accessors_raise_clearly() -> None:
    await dispose_engine()
    await dispose_redis()
    with pytest.raises(RuntimeError, match="not initialised"):
        get_engine()
    with pytest.raises(RuntimeError, match="not initialised"):
        get_redis()
    with pytest.raises(RuntimeError, match="not initialised"):
        await anext(get_session())


async def test_lifespan_brings_everything_up_and_ready_is_200(settings: Settings) -> None:
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with (
        AsyncClient(transport=transport, base_url="http://test") as client,
        app.router.lifespan_context(app),
    ):
        response = await client.get("/health/ready")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ok"
