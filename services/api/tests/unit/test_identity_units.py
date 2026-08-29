"""Rate limiting, phone normalisation, SMS adapters and JWT.

The rate limiter's degradation policy is the interesting part: it fails OPEN for
OTP requests and CLOSED for verify attempts, and that asymmetry is deliberate.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import jwt
import pytest

from app.core.config import Environment, Settings, get_settings
from app.modules.identity.ratelimit import (
    OTP_PER_IP,
    OTP_PER_PHONE,
    VERIFY_PER_IP,
    RateLimit,
    RateLimiter,
)
from app.modules.identity.schemas import (
    OtpRequest,
    OtpVerify,
    PlayPinSet,
    normalise_phone,
)
from app.modules.identity.security import (
    decode_access_token,
    issue_access_token,
    needs_rehash,
)
from app.modules.identity.sms import (
    LocalAggregatorSms,
    NullSms,
    TwilioSms,
    build_sms_provider,
)

# --- fake redis -------------------------------------------------------------


class FakePipeline:
    def __init__(self, store: dict[str, dict[str, float]]) -> None:
        self.store = store
        self.ops: list[tuple[str, tuple[Any, ...]]] = []

    def zremrangebyscore(self, key: str, low: float, high: float) -> None:
        self.ops.append(("trim", (key, low, high)))

    def zcard(self, key: str) -> None:
        self.ops.append(("count", (key,)))

    def zadd(self, key: str, mapping: dict[str, float]) -> None:
        self.ops.append(("add", (key, mapping)))

    def expire(self, key: str, seconds: int) -> None:
        self.ops.append(("expire", (key, seconds)))

    async def execute(self) -> list[Any]:
        results: list[Any] = []
        for op, args in self.ops:
            if op == "trim":
                key, low, high = args
                bucket = self.store.setdefault(key, {})
                for member in [m for m, score in bucket.items() if low <= score <= high]:
                    del bucket[member]
                results.append(0)
            elif op == "count":
                results.append(len(self.store.get(args[0], {})))
            elif op == "add":
                key, mapping = args
                self.store.setdefault(key, {}).update(mapping)
                results.append(len(mapping))
            else:
                results.append(True)
        self.ops.clear()
        return results


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, dict[str, float]] = {}

    def pipeline(self) -> FakePipeline:
        return FakePipeline(self.store)


class BrokenRedis:
    def pipeline(self) -> Any:
        raise ConnectionError("redis is unreachable")


# --- rate limiting ----------------------------------------------------------


async def test_a_sliding_window_allows_exactly_the_limit() -> None:
    limiter = RateLimiter(FakeRedis())  # type: ignore[arg-type]
    limit = RateLimit("test", 3)
    assert [await limiter.check(limit, "id") for _ in range(3)] == [True, True, True]
    assert await limiter.check(limit, "id") is False


async def test_concurrent_requests_each_consume_one_slot() -> None:
    """A collapsed set entry would silently double the effective limit."""
    limiter = RateLimiter(FakeRedis())  # type: ignore[arg-type]
    limit = RateLimit("test", 5)
    import asyncio

    results = await asyncio.gather(*[limiter.check(limit, "same") for _ in range(8)])
    assert sum(results) == 5, f"allowed {sum(results)} of 8, expected exactly 5"


async def test_different_identities_have_separate_windows() -> None:
    limiter = RateLimiter(FakeRedis())  # type: ignore[arg-type]
    limit = RateLimit("test", 1)
    assert await limiter.check(limit, "a") is True
    assert await limiter.check(limit, "b") is True
    assert await limiter.check(limit, "a") is False


async def test_otp_requests_fail_open_when_redis_is_down() -> None:
    """A caregiver must still be able to log in during a cache outage."""
    limiter = RateLimiter(BrokenRedis())  # type: ignore[arg-type]
    assert await limiter.check(OTP_PER_PHONE, PHONE_ID) is True
    assert await limiter.check(OTP_PER_IP, "1.1.1.1") is True


async def test_verify_attempts_fail_closed_when_redis_is_down() -> None:
    """An outage must not become an unbounded brute-force window."""
    limiter = RateLimiter(BrokenRedis())  # type: ignore[arg-type]
    assert await limiter.check(VERIFY_PER_IP, "1.1.1.1") is False


PHONE_ID = "+201001234567"


def test_the_configured_limits_match_the_specification() -> None:
    assert OTP_PER_PHONE.limit == 3
    assert OTP_PER_IP.limit == 10
    assert VERIFY_PER_IP.limit == 10
    assert OTP_PER_PHONE.fail_open is True
    assert VERIFY_PER_IP.fail_open is False


# --- phone normalisation ----------------------------------------------------


@pytest.mark.parametrize(
    "written",
    ["+201001234567", "01001234567", "0100 123 4567", "00201001234567", "+20 100 123 4567"],
)
def test_the_same_egyptian_number_normalises_to_one_form(written: str) -> None:
    """If three spellings hashed to three keys, the 3-per-hour cap is bypassed."""
    assert normalise_phone(written) == "+201001234567"


@pytest.mark.parametrize("bad", ["123", "not a number", "", "+9999999999999999"])
def test_an_invalid_number_is_rejected(bad: str) -> None:
    with pytest.raises(ValueError, match="valid phone number"):
        normalise_phone(bad)


def test_the_request_schema_normalises_on_the_way_in() -> None:
    assert OtpRequest(phone_e164="01001234567").phone_e164 == "+201001234567"


def test_a_non_six_digit_code_is_rejected_by_the_schema() -> None:
    from pydantic import ValidationError

    for bad in ("12345", "abcdef", "12 45 6"):
        with pytest.raises(ValidationError):
            OtpVerify(phone_e164=PHONE_ID, code=bad)
    assert OtpVerify(phone_e164=PHONE_ID, code="483920").code == "483920"


def test_a_non_four_digit_pin_is_rejected_by_the_schema() -> None:
    from pydantic import ValidationError

    for bad in ("123", "12345", "abcd"):
        with pytest.raises(ValidationError):
            PlayPinSet(pin=bad)
    assert PlayPinSet(pin="0000").pin == "0000"


def test_the_schemas_forbid_unexpected_fields() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        OtpRequest(phone_e164=PHONE_ID, admin=True)  # type: ignore[call-arg]


# --- SMS adapters -----------------------------------------------------------


async def test_null_sms_records_rather_than_sends() -> None:
    sms = NullSms()
    assert await sms.send(phone_e164=PHONE_ID, message="كود: 123456") is True
    assert sms.sent == [(PHONE_ID, "كود: 123456")]


async def test_the_real_adapters_refuse_rather_than_pretending(
    settings: Settings | None = None,
) -> None:
    """A provider that claims success without sending is worse than one that fails."""
    get_settings.cache_clear()
    resolved = get_settings()
    for adapter in (TwilioSms(resolved), LocalAggregatorSms(resolved)):
        with pytest.raises(NotImplementedError, match=r"SETUP.md"):
            await adapter.send(phone_e164=PHONE_ID, message="x")


def test_the_provider_factory_defaults_to_null() -> None:
    get_settings.cache_clear()
    resolved = get_settings()
    assert build_sms_provider(resolved).name == "null"
    assert build_sms_provider(resolved.model_copy(update={"sms_provider": "twilio"})).name == (
        "twilio"
    )
    assert (
        build_sms_provider(resolved.model_copy(update={"sms_provider": "local_aggregator"})).name
        == "local_aggregator"
    )
    assert (
        build_sms_provider(resolved.model_copy(update={"sms_provider": "nonsense"})).name == "null"
    )


# --- JWT --------------------------------------------------------------------


def test_an_access_token_carries_exactly_the_documented_claims() -> None:
    get_settings.cache_clear()
    caregiver_id = uuid.uuid4()
    token, expires_in = issue_access_token(caregiver_id=caregiver_id)
    claims = decode_access_token(token)

    assert claims["sub"] == str(caregiver_id)
    assert claims["cgid"] == str(caregiver_id)
    assert claims["scope"] == "caregiver"
    assert claims["jti"]
    assert expires_in == 900


def test_two_tokens_have_different_jti_values() -> None:
    """A reused jti would break any future replay detection."""
    get_settings.cache_clear()
    caregiver_id = uuid.uuid4()
    first = decode_access_token(issue_access_token(caregiver_id=caregiver_id)[0])
    second = decode_access_token(issue_access_token(caregiver_id=caregiver_id)[0])
    assert first["jti"] != second["jti"]


def test_nbf_is_backdated_so_a_fast_client_clock_still_works() -> None:
    """A device 30 seconds fast must not reject its own fresh token."""
    get_settings.cache_clear()
    now = dt.datetime.now(dt.UTC)
    token, _ = issue_access_token(caregiver_id=uuid.uuid4(), now=now)
    claims = decode_access_token(token)
    assert claims["nbf"] < claims["iat"]
    assert claims["iat"] - claims["nbf"] == 60


def test_an_expired_token_is_rejected() -> None:
    get_settings.cache_clear()
    past = dt.datetime.now(dt.UTC) - dt.timedelta(hours=2)
    token, _ = issue_access_token(caregiver_id=uuid.uuid4(), now=past)
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(token)


def test_a_tampered_token_is_rejected() -> None:
    get_settings.cache_clear()
    token, _ = issue_access_token(caregiver_id=uuid.uuid4())
    header, payload, signature = token.split(".")
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(f"{header}.{payload}.{signature[:-4]}AAAA")


def test_a_token_signed_with_the_wrong_algorithm_is_rejected() -> None:
    """The classic 'alg: none' downgrade."""
    get_settings.cache_clear()
    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "jti": "x", "exp": 9999999999}, "", algorithm="none"
    )
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(forged)


def test_argon2_hashes_do_not_immediately_need_rehashing() -> None:
    from app.modules.identity.security import hash_secret

    assert needs_rehash(hash_secret("1234")) is False


def test_production_refuses_to_start_without_real_keys() -> None:
    """A local-dev default must never silently become a production secret."""
    with pytest.raises(ValueError, match="production"):
        Settings(
            environment=Environment.PRODUCTION,
            database_url="postgresql+asyncpg://u:p@h:5432/d",  # type: ignore[arg-type]
            redis_url="redis://h:6379/0",  # type: ignore[arg-type]
            s3_endpoint_url="http://h",
            s3_region="r",
            s3_bucket="b",
            s3_access_key_id="k",
            s3_secret_access_key="s",
        )


def test_production_starts_when_every_secret_is_supplied() -> None:
    settings = Settings(
        environment=Environment.PRODUCTION,
        database_url="postgresql+asyncpg://u:p@h:5432/d",  # type: ignore[arg-type]
        redis_url="redis://h:6379/0",  # type: ignore[arg-type]
        s3_endpoint_url="http://h",
        s3_region="r",
        s3_bucket="b",
        s3_access_key_id="k",
        s3_secret_access_key="s",
        otp_pepper="a-real-pepper",
        invite_secret="a-real-invite-secret",
        jwt_private_key="-----BEGIN PRIVATE KEY-----",
        jwt_public_key="-----BEGIN PUBLIC KEY-----",
    )
    assert settings.is_production
    assert settings.debug_docs_enabled is False
