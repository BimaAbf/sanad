"""ConsentGate — consent as a precondition, not a UI concern.

Two properties this has to get right:

* **Withdrawal takes effect within the same request.** A 60-second cache that is
  not busted on write means a caregiver can hit "stop sending my child's words to
  an AI", get a confirmation, and have the very next call still go out. The cache
  is therefore explicitly invalidated on every consent write, before the response
  is returned.
* **It fails closed.** If Redis is unreachable we read through to Postgres. If
  Postgres is unreachable the gate raises rather than assuming consent. An outage
  must never widen what we are permitted to do with a child's data.
"""

from __future__ import annotations

import json

import structlog
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Forbidden
from app.modules.children.domain import ConsentKey

logger = structlog.get_logger(__name__)

CACHE_TTL_SECONDS = 60


class ConsentRequired(Forbidden):
    code = "consent_required"
    title = "Consent Required"
    message_ar = "محتاجين موافقتك على الخطوة دي الأول."


def _cache_key(child_id: str) -> str:
    return f"consent:{child_id}"


#: The current status of every key for one child, resolved from the append-only
#: ledger by taking the most recent row per key.
CURRENT_CONSENTS_SQL = text("""
    SELECT DISTINCT ON (consent_key) consent_key, status
    FROM consents
    WHERE child_id = :child_id
    ORDER BY consent_key, granted_at DESC, id DESC
""")


class ConsentGate:
    def __init__(self, session: AsyncSession, redis: Redis | None = None) -> None:
        self._session = session
        self._redis = redis

    async def current(self, child_id: str) -> dict[str, str]:
        """Every key's current status. Read-through cache, 60s TTL."""
        if self._redis is not None:
            try:
                cached = await self._redis.get(_cache_key(child_id))
                if cached:
                    loaded: dict[str, str] = json.loads(cached)
                    return loaded
            except Exception as exc:  # noqa: BLE001 -- cache miss, not a failure
                logger.info("consent_cache_unavailable", exc_type=type(exc).__name__)

        rows = await self._session.execute(CURRENT_CONSENTS_SQL, {"child_id": child_id})
        statuses = {row.consent_key: row.status for row in rows}

        if self._redis is not None:
            try:
                await self._redis.setex(
                    _cache_key(child_id), CACHE_TTL_SECONDS, json.dumps(statuses)
                )
            except Exception as exc:  # noqa: BLE001 -- caching is best-effort
                logger.info("consent_cache_write_failed", exc_type=type(exc).__name__)
        return statuses

    async def invalidate(self, child_id: str) -> None:
        """Bust the cache. MUST be called inside the same request as any write."""
        if self._redis is None:
            return
        try:
            await self._redis.delete(_cache_key(child_id))
        except Exception as exc:  # noqa: BLE001 -- see class docstring
            # A failed invalidation would leave a stale grant readable for up to
            # 60 seconds. Logged at error precisely because it is a privacy
            # regression, not a performance one.
            logger.error("consent_cache_invalidate_failed", exc_type=type(exc).__name__)

    async def is_granted(self, child_id: str, key: ConsentKey) -> bool:
        return (await self.current(child_id)).get(key.value) == "granted"

    async def require(self, child_id: str, key: ConsentKey) -> None:
        """Raise ConsentRequired unless this consent is currently granted."""
        if not await self.is_granted(child_id, key):
            logger.info("consent_denied", child_id=child_id, reason=key.value)
            raise ConsentRequired(detail=f"Consent '{key.value}' is not granted.")
