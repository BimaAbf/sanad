from __future__ import annotations

import pytest
from fastapi import APIRouter
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import create_app


@pytest.fixture
def app_instance():  # type: ignore[no-untyped-def]
    get_settings.cache_clear()
    application = create_app(get_settings())

    router = APIRouter()

    @router.get("/__boom")
    async def boom() -> None:
        raise ValueError("this message must never reach a caregiver")

    application.include_router(router)
    return application


async def _client(application):  # type: ignore[no-untyped-def]
    return AsyncClient(
        transport=ASGITransport(app=application, raise_app_exceptions=False),
        base_url="http://test",
    )


async def test_health_has_no_dependencies(app_instance) -> None:  # type: ignore[no-untyped-def]
    # No lifespan is run, so no engine or redis client exists. /health must
    # still answer 200 — that is the whole point of separating it from /ready.
    async with await _client(app_instance) as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_health_ready_reports_each_dependency(app_instance) -> None:  # type: ignore[no-untyped-def]
    async with await _client(app_instance) as client:
        response = await client.get("/health/ready")
    body = response.json()
    assert set(body["checks"]) == {"db", "redis", "s3"}
    for name, check in body["checks"].items():
        assert "status" in check, name
    # Without a lifespan the dependencies are uninitialised, so readiness is 503.
    assert response.status_code == 503
    assert body["status"] == "degraded"


async def test_unhandled_exception_is_problem_details(app_instance) -> None:  # type: ignore[no-untyped-def]
    async with await _client(app_instance) as client:
        response = await client.get("/__boom")
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["message_ar"]
    assert body["code"] == "internal_error"
    assert body["request_id"]
    assert "ValueError" not in response.text
    assert "must never reach a caregiver" not in response.text
    assert "Traceback" not in response.text


async def test_not_found_is_problem_details_with_arabic(app_instance) -> None:  # type: ignore[no-untyped-def]
    async with await _client(app_instance) as client:
        response = await client.get("/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "not_found"
    assert body["message_ar"] == "مش لاقيين الحاجة دي."


async def test_security_headers_present(app_instance) -> None:  # type: ignore[no-untyped-def]
    async with await _client(app_instance) as client:
        response = await client.get("/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Request-Id"]
