"""Redis sliding-window rate limiting.

A sliding window rather than a fixed bucket: a fixed hourly bucket lets an
attacker send 3 requests at 10:59 and 3 more at 11:00. The implementation is a
sorted set of request timestamps, trimmed to the window on every check.

If Redis is unavailable the limiter **fails open** for OTP *requests* (a
caregiver must still be able to log in during a cache outage) and **fails
closed** for verify attempts (an outage must not become an unlimited brute-force
window). That asymmetry is deliberate; see docs/adr/002-auth.md.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import structlog
from redis.asyncio import Redis

logger = structlog.get_logger(__name__)

WINDOW_SECONDS = 3600


@dataclass(frozen=True, slots=True)
class RateLimit:
    key_prefix: str
    limit: int
    window_seconds: int = WINDOW_SECONDS
    #: What to do when Redis itself is unreachable.
    fail_open: bool = True


class RateLimiter:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def check(self, limit: RateLimit, identity: str) -> bool:
        """True if this request is within the limit. Records it if so."""
        key = f"rl:{limit.key_prefix}:{identity}"
        now = time.time()
        cutoff = now - limit.window_seconds
        try:
            pipe = self._redis.pipeline()
            pipe.zremrangebyscore(key, 0, cutoff)
            pipe.zcard(key)
            results = await pipe.execute()
            used = int(results[1])
            if used >= limit.limit:
                logger.info("rate_limited", reason=limit.key_prefix, count=used)
                return False
            pipe = self._redis.pipeline()
            # The member must be unique per request or concurrent calls collapse
            # into one set entry and the limit silently doubles.
            pipe.zadd(key, {f"{now}:{id(limit)}:{used}": now})
            pipe.expire(key, limit.window_seconds)
            await pipe.execute()
            return True
        except Exception as exc:  # noqa: BLE001 -- degradation policy, see docstring
            logger.error(
                "rate_limiter_unavailable",
                reason=limit.key_prefix,
                exc_type=type(exc).__name__,
            )
            return limit.fail_open


OTP_PER_PHONE = RateLimit("otp:phone", 3, fail_open=True)
OTP_PER_IP = RateLimit("otp:ip", 10, fail_open=True)
# Fails CLOSED: a Redis outage must not become an unbounded brute-force window.
VERIFY_PER_IP = RateLimit("otp:verify:ip", 10, fail_open=False)
