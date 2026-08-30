"""Redis connection pool and readiness probe."""

from __future__ import annotations

from typing import Any

from redis.asyncio import Redis

from app.core.config import Settings

_client: Redis | None = None


def init_redis(settings: Settings) -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(
            str(settings.redis_url),
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            health_check_interval=30,
        )
    return _client


async def dispose_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


def get_redis() -> Redis:
    if _client is None:
        raise RuntimeError("Redis client not initialised; call init_redis() first.")
    return _client


async def check_redis(client: Redis | None = None) -> dict[str, Any]:
    """Readiness probe for Redis. Never raises."""
    try:
        target = client or get_redis()
        await target.ping()
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001 -- probe reports, never propagates
        return {"status": "error", "reason": type(exc).__name__}
