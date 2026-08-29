"""P01 acceptance criteria, against in-memory repositories.

These are business rules, not SQL, so they are tested without a database. The
four that matter most:

  * 100 sequential wrong OTP codes never succeed and lock after 3
  * reusing a consumed refresh token revokes the entire family
  * /auth/otp/request has statistically indistinguishable latency for existing
    and non-existing numbers
  * no secret, code, token or hash appears in logs at DEBUG level

The last one is asserted by capturing real log output during a full auth flow
and grepping it, exactly as P01 specifies.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import logging
import statistics
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest
import structlog

from app.core.config import Settings, get_settings
from app.core.errors import Forbidden, RateLimited
from app.core.logging import configure_logging
from app.modules.identity import domain
from app.modules.identity.service import (
    IdentityService,
    InvalidCredentials,
    OtpLocked,
    PinLocked,
    RefreshReuseDetected,
)
from app.modules.identity.sms import NullSms

PHONE = "+201001234567"
OTHER_PHONE = "+201009999999"


# --- in-memory doubles ------------------------------------------------------


@dataclass
class FakeCaregiver:
    id: uuid.UUID
    phone_e164: str | None = None
    email: str | None = None
    display_name: str = ""
    relationship: str | None = None
    governorate: str | None = None
    locale: str = "ar-EG"
    play_pin_hash: str | None = None
    last_login_at: dt.datetime | None = None


@dataclass
class FakeOtp:
    id: uuid.UUID
    phone_e164: str
    code_hash: str
    expires_at: dt.datetime
    attempts: int = 0
    consumed_at: dt.datetime | None = None


@dataclass
class FakeRefresh:
    id: uuid.UUID
    caregiver_id: uuid.UUID
    token_hash: str
    family_id: uuid.UUID
    expires_at: dt.datetime
    revoked_at: dt.datetime | None = None


@dataclass
class FakeLink:
    caregiver_id: uuid.UUID
    child_id: uuid.UUID
    role: str


@dataclass
class FakePinAttempts:
    caregiver_id: uuid.UUID
    failed_attempts: int = 0
    locked_until: dt.datetime | None = None


@dataclass
class FakeRepo:
    """Everything IdentityRepository does, in memory. Same semantics, no SQL."""

    caregivers: dict[uuid.UUID, FakeCaregiver] = field(default_factory=dict)
    otps: list[FakeOtp] = field(default_factory=list)
    refresh: dict[str, FakeRefresh] = field(default_factory=dict)
    links: dict[tuple[uuid.UUID, uuid.UUID], FakeLink] = field(default_factory=dict)
    pins: dict[uuid.UUID, FakePinAttempts] = field(default_factory=dict)

    async def get_caregiver(self, caregiver_id: uuid.UUID) -> FakeCaregiver | None:
        return self.caregivers.get(caregiver_id)

    async def find_caregiver_by_phone(self, phone_e164: str) -> FakeCaregiver | None:
        for caregiver in self.caregivers.values():
            if caregiver.phone_e164 == phone_e164:
                return caregiver
        return None

    async def create_caregiver(self, *, phone_e164: str) -> FakeCaregiver:
        caregiver = FakeCaregiver(id=uuid.uuid4(), phone_e164=phone_e164)
        self.caregivers[caregiver.id] = caregiver
        return caregiver

    async def touch_last_login(self, caregiver_id: uuid.UUID, now: dt.datetime) -> None:
        if caregiver_id in self.caregivers:
            self.caregivers[caregiver_id].last_login_at = now

    async def create_otp(
        self, *, phone_e164: str, code_hash: str, expires_at: dt.datetime, created_ip: Any
    ) -> FakeOtp:
        otp = FakeOtp(
            id=uuid.uuid4(),
            phone_e164=phone_e164,
            code_hash=code_hash,
            expires_at=expires_at,
        )
        self.otps.append(otp)
        return otp

    async def latest_unconsumed_otp(self, phone_e164: str) -> FakeOtp | None:
        for otp in reversed(self.otps):
            if otp.phone_e164 == phone_e164 and otp.consumed_at is None:
                return otp
        return None

    async def increment_otp_attempts(self, otp_id: uuid.UUID) -> None:
        for otp in self.otps:
            if otp.id == otp_id:
                otp.attempts += 1

    async def consume_otp(self, otp_id: uuid.UUID, now: dt.datetime) -> None:
        for otp in self.otps:
            if otp.id == otp_id:
                otp.consumed_at = now

    async def create_refresh_token(
        self,
        *,
        caregiver_id: uuid.UUID,
        token_hash: str,
        family_id: uuid.UUID,
        expires_at: dt.datetime,
        user_agent: str | None,
    ) -> FakeRefresh:
        record = FakeRefresh(
            id=uuid.uuid4(),
            caregiver_id=caregiver_id,
            token_hash=token_hash,
            family_id=family_id,
            expires_at=expires_at,
        )
        self.refresh[token_hash] = record
        return record

    async def find_refresh_token(self, token_hash: str) -> FakeRefresh | None:
        return self.refresh.get(token_hash)

    async def revoke_refresh_token(self, token_id: uuid.UUID, now: dt.datetime) -> None:
        for record in self.refresh.values():
            if record.id == token_id and record.revoked_at is None:
                record.revoked_at = now

    async def revoke_family(self, family_id: uuid.UUID, now: dt.datetime) -> int:
        count = 0
        for record in self.refresh.values():
            if record.family_id == family_id and record.revoked_at is None:
                record.revoked_at = now
                count += 1
        return count

    async def get_link(self, *, caregiver_id: uuid.UUID, child_id: uuid.UUID) -> FakeLink | None:
        return self.links.get((caregiver_id, child_id))

    async def list_links(self, caregiver_id: uuid.UUID) -> list[FakeLink]:
        return [link for key, link in self.links.items() if key[0] == caregiver_id]

    async def link_child(
        self, *, caregiver_id: uuid.UUID, child_id: uuid.UUID, role: str, invited_by: Any
    ) -> FakeLink:
        link = FakeLink(caregiver_id=caregiver_id, child_id=child_id, role=role)
        self.links[(caregiver_id, child_id)] = link
        return link

    async def get_pin_attempts(self, caregiver_id: uuid.UUID) -> FakePinAttempts | None:
        return self.pins.get(caregiver_id)

    async def upsert_pin_attempts(
        self,
        *,
        caregiver_id: uuid.UUID,
        failed_attempts: int,
        locked_until: dt.datetime | None,
        now: dt.datetime,
    ) -> None:
        self.pins[caregiver_id] = FakePinAttempts(
            caregiver_id=caregiver_id,
            failed_attempts=failed_attempts,
            locked_until=locked_until,
        )

    async def set_play_pin(self, caregiver_id: uuid.UUID, pin_hash: str) -> None:
        self.caregivers[caregiver_id].play_pin_hash = pin_hash


class AllowAllLimiter:
    async def check(self, _limit: Any, _identity: str) -> bool:
        return True


class DenyAllLimiter:
    async def check(self, _limit: Any, _identity: str) -> bool:
        return False


@pytest.fixture
def settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
def sms() -> NullSms:
    return NullSms()


@pytest.fixture
def repo() -> FakeRepo:
    return FakeRepo()


@pytest.fixture
def service(repo: FakeRepo, sms: NullSms, settings: Settings) -> IdentityService:
    return IdentityService(
        repo=repo,  # type: ignore[arg-type]
        limiter=AllowAllLimiter(),  # type: ignore[arg-type]
        sms=sms,
        settings=settings,
    )


def _code_from(sms: NullSms) -> str:
    """Pull the code out of the message NullSms recorded."""
    import re

    body = sms.sent[-1][1]
    match = re.search(r"\d{6}", body)
    assert match, body
    return match.group(0)


# ============================================================================
# The full cycle
# ============================================================================


async def test_register_login_refresh_logout(
    service: IdentityService, repo: FakeRepo, sms: NullSms
) -> None:
    """P01: full OTP register -> login -> refresh -> logout cycle works."""
    await service.request_otp(phone_e164=PHONE, client_ip="1.1.1.1")
    tokens = await service.verify_otp(
        phone_e164=PHONE, code=_code_from(sms), client_ip="1.1.1.1", user_agent="t"
    )
    assert tokens.is_new_user is True
    assert tokens.access_token
    assert tokens.refresh_token

    # Log in again: the same caregiver, not a new one.
    await service.request_otp(phone_e164=PHONE, client_ip="1.1.1.1")
    second = await service.verify_otp(
        phone_e164=PHONE, code=_code_from(sms), client_ip="1.1.1.1", user_agent="t"
    )
    assert second.is_new_user is False
    assert len(repo.caregivers) == 1

    rotated = await service.refresh(refresh_token=second.refresh_token, user_agent="t")
    assert rotated.refresh_token != second.refresh_token
    assert rotated.access_token

    await service.logout(refresh_token=rotated.refresh_token)
    with pytest.raises(RefreshReuseDetected):
        await service.refresh(refresh_token=rotated.refresh_token, user_agent="t")


# ============================================================================
# OTP brute force
# ============================================================================


async def test_one_hundred_wrong_codes_never_succeed_and_lock_after_three(
    service: IdentityService, repo: FakeRepo, sms: NullSms
) -> None:
    """P01, verbatim: '100 sequential wrong OTP codes never succeed and lock
    after 3'.
    """
    await service.request_otp(phone_e164=PHONE, client_ip="1.1.1.1")
    real_code = _code_from(sms)

    locked_at: int | None = None
    for attempt in range(100):
        guess = f"{attempt:06d}"
        if guess == real_code:  # pragma: no cover -- vanishingly unlikely
            continue
        with pytest.raises((InvalidCredentials, OtpLocked)) as excinfo:
            await service.verify_otp(
                phone_e164=PHONE, code=guess, client_ip="1.1.1.1", user_agent="t"
            )
        if isinstance(excinfo.value, OtpLocked) and locked_at is None:
            locked_at = attempt

    assert locked_at == domain.OTP_MAX_ATTEMPTS, (
        f"locked after {locked_at} wrong codes, expected {domain.OTP_MAX_ATTEMPTS}"
    )
    # And the real code no longer works either — the OTP is spent.
    with pytest.raises(OtpLocked):
        await service.verify_otp(
            phone_e164=PHONE, code=real_code, client_ip="1.1.1.1", user_agent="t"
        )
    assert repo.caregivers == {}, "no account was created by a failed brute force"


async def test_an_expired_code_is_refused(
    service: IdentityService, repo: FakeRepo, sms: NullSms
) -> None:
    await service.request_otp(phone_e164=PHONE, client_ip=None)
    repo.otps[-1].expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)
    with pytest.raises(InvalidCredentials):
        await service.verify_otp(
            phone_e164=PHONE, code=_code_from(sms), client_ip=None, user_agent=None
        )


async def test_a_consumed_code_cannot_be_replayed(service: IdentityService, sms: NullSms) -> None:
    await service.request_otp(phone_e164=PHONE, client_ip=None)
    code = _code_from(sms)
    await service.verify_otp(phone_e164=PHONE, code=code, client_ip=None, user_agent=None)
    with pytest.raises(InvalidCredentials):
        await service.verify_otp(phone_e164=PHONE, code=code, client_ip=None, user_agent=None)


async def test_verifying_with_no_pending_code_fails_cleanly(
    service: IdentityService,
) -> None:
    with pytest.raises(InvalidCredentials):
        await service.verify_otp(phone_e164=PHONE, code="000000", client_ip=None, user_agent=None)


async def test_a_second_request_supersedes_the_first_code(
    service: IdentityService, sms: NullSms
) -> None:
    """Two valid codes must not be in flight at once."""
    await service.request_otp(phone_e164=PHONE, client_ip=None)
    first = _code_from(sms)
    await service.request_otp(phone_e164=PHONE, client_ip=None)
    second = _code_from(sms)
    assert first != second

    with pytest.raises(InvalidCredentials):
        await service.verify_otp(phone_e164=PHONE, code=first, client_ip=None, user_agent=None)
    tokens = await service.verify_otp(
        phone_e164=PHONE, code=second, client_ip=None, user_agent=None
    )
    assert tokens.access_token


async def test_rate_limits_produce_a_clean_429(
    repo: FakeRepo, sms: NullSms, settings: Settings
) -> None:
    service = IdentityService(
        repo=repo,  # type: ignore[arg-type]
        limiter=DenyAllLimiter(),  # type: ignore[arg-type]
        sms=sms,
        settings=settings,
    )
    with pytest.raises(RateLimited):
        await service.request_otp(phone_e164=PHONE, client_ip="1.1.1.1")
    with pytest.raises(RateLimited):
        await service.verify_otp(
            phone_e164=PHONE, code="123456", client_ip="1.1.1.1", user_agent=None
        )


# ============================================================================
# Enumeration resistance
# ============================================================================


async def test_request_otp_latency_does_not_reveal_whether_a_number_exists(
    service: IdentityService, repo: FakeRepo, sms: NullSms
) -> None:
    """P01: 'statistically indistinguishable latency for existing and
    non-existing numbers (mean difference < 20ms over 50 calls each)'.
    """
    # Register one number so the two cases genuinely differ in the database.
    await service.request_otp(phone_e164=PHONE, client_ip=None)
    await service.verify_otp(
        phone_e164=PHONE, code=_code_from(sms), client_ip=None, user_agent=None
    )
    assert await repo.find_caregiver_by_phone(PHONE) is not None
    assert await repo.find_caregiver_by_phone(OTHER_PHONE) is None

    async def timed(phone: str) -> float:
        started = time.perf_counter()
        await service.request_otp(phone_e164=phone, client_ip=None)
        await service.enumeration_jitter()
        return (time.perf_counter() - started) * 1000

    existing = [await timed(PHONE) for _ in range(50)]
    missing = [await timed(OTHER_PHONE) for _ in range(50)]

    difference = abs(statistics.mean(existing) - statistics.mean(missing))
    assert difference < 20, (
        f"mean latency differed by {difference:.1f}ms — that is an enumeration "
        f"oracle (existing {statistics.mean(existing):.1f}ms, "
        f"missing {statistics.mean(missing):.1f}ms)"
    )


async def test_the_jitter_stays_within_its_stated_bounds() -> None:
    low, high = domain.ENUMERATION_JITTER_MS
    for _ in range(20):
        started = time.perf_counter()
        await IdentityService.enumeration_jitter()
        elapsed = (time.perf_counter() - started) * 1000
        # A generous upper bound: the event loop adds scheduling overhead.
        assert elapsed >= low * 0.8, elapsed
        assert elapsed < high + 120, elapsed


# ============================================================================
# Refresh rotation and reuse detection
# ============================================================================


async def test_reusing_a_consumed_refresh_token_revokes_the_whole_family(
    service: IdentityService, repo: FakeRepo, sms: NullSms
) -> None:
    """P01: 'reusing a consumed refresh token revokes the family; the old access
    token still works until expiry but no new one can be minted'.
    """
    await service.request_otp(phone_e164=PHONE, client_ip=None)
    first = await service.verify_otp(
        phone_e164=PHONE, code=_code_from(sms), client_ip=None, user_agent=None
    )
    second = await service.refresh(refresh_token=first.refresh_token, user_agent=None)
    third = await service.refresh(refresh_token=second.refresh_token, user_agent=None)

    # An attacker replays the FIRST token, which was consumed two rotations ago.
    with pytest.raises(RefreshReuseDetected):
        await service.refresh(refresh_token=first.refresh_token, user_agent=None)

    # Every token in the family is now dead, including the legitimate current one.
    assert all(record.revoked_at is not None for record in repo.refresh.values())
    with pytest.raises(RefreshReuseDetected):
        await service.refresh(refresh_token=third.refresh_token, user_agent=None)

    # The already-issued access token is still structurally valid until it
    # expires — that is the documented trade-off, not an oversight.
    from app.modules.identity.security import decode_access_token

    claims = decode_access_token(third.access_token)
    assert claims["sub"]


async def test_every_rotation_stays_in_the_same_family(
    service: IdentityService, repo: FakeRepo, sms: NullSms
) -> None:
    await service.request_otp(phone_e164=PHONE, client_ip=None)
    tokens = await service.verify_otp(
        phone_e164=PHONE, code=_code_from(sms), client_ip=None, user_agent=None
    )
    for _ in range(5):
        tokens = await service.refresh(refresh_token=tokens.refresh_token, user_agent=None)
    families = {record.family_id for record in repo.refresh.values()}
    assert len(families) == 1, "rotation must not start a new family"
    assert len(repo.refresh) == 6


async def test_an_unknown_refresh_token_is_refused(service: IdentityService) -> None:
    with pytest.raises(InvalidCredentials):
        await service.refresh(refresh_token="never-issued", user_agent=None)


async def test_an_expired_refresh_token_is_refused_and_revoked(
    service: IdentityService, repo: FakeRepo, sms: NullSms
) -> None:
    await service.request_otp(phone_e164=PHONE, client_ip=None)
    tokens = await service.verify_otp(
        phone_e164=PHONE, code=_code_from(sms), client_ip=None, user_agent=None
    )
    stored = repo.refresh[domain.hash_refresh_token(tokens.refresh_token)]
    stored.expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)

    with pytest.raises(InvalidCredentials):
        await service.refresh(refresh_token=tokens.refresh_token, user_agent=None)
    assert stored.revoked_at is not None


async def test_logout_without_a_cookie_is_a_no_op(service: IdentityService) -> None:
    await service.logout(refresh_token=None)
    await service.logout(refresh_token="not-a-real-token")


# ============================================================================
# Child authorisation
# ============================================================================


async def test_an_unlinked_child_is_403_and_a_linked_one_is_allowed(
    service: IdentityService, repo: FakeRepo
) -> None:
    """P01: 'require_child_access returns 403 for an unlinked child'."""
    caregiver_id = uuid.uuid4()
    linked = uuid.uuid4()
    unlinked = uuid.uuid4()
    repo.links[(caregiver_id, linked)] = FakeLink(caregiver_id, linked, "owner")

    role = await service.assert_child_access(
        caregiver_id=caregiver_id, child_id=linked, min_role=domain.Role.CO_CAREGIVER
    )
    assert role is domain.Role.OWNER

    with pytest.raises(Forbidden):
        await service.assert_child_access(
            caregiver_id=caregiver_id,
            child_id=unlinked,
            min_role=domain.Role.CO_CAREGIVER,
        )


async def test_a_nonexistent_child_is_indistinguishable_from_someone_elses(
    service: IdentityService,
) -> None:
    """Otherwise anyone could enumerate which child ids exist."""
    caregiver_id = uuid.uuid4()
    errors = []
    for _ in range(2):
        with pytest.raises(Forbidden) as excinfo:
            await service.assert_child_access(
                caregiver_id=caregiver_id,
                child_id=uuid.uuid4(),
                min_role=domain.Role.CO_CAREGIVER,
            )
        errors.append((excinfo.value.status, excinfo.value.code, excinfo.value.message_ar))
    assert errors[0] == errors[1]


async def test_a_co_caregiver_cannot_perform_an_owner_action(
    service: IdentityService, repo: FakeRepo
) -> None:
    caregiver_id = uuid.uuid4()
    child_id = uuid.uuid4()
    repo.links[(caregiver_id, child_id)] = FakeLink(caregiver_id, child_id, "co_caregiver")

    await service.assert_child_access(
        caregiver_id=caregiver_id, child_id=child_id, min_role=domain.Role.CO_CAREGIVER
    )
    with pytest.raises(Forbidden):
        await service.assert_child_access(
            caregiver_id=caregiver_id, child_id=child_id, min_role=domain.Role.OWNER
        )


async def test_a_therapist_is_refused_the_default_gate(
    service: IdentityService, repo: FakeRepo
) -> None:
    """A therapist ranks below a co-caregiver and must be granted explicitly."""
    caregiver_id = uuid.uuid4()
    child_id = uuid.uuid4()
    repo.links[(caregiver_id, child_id)] = FakeLink(caregiver_id, child_id, "therapist")
    with pytest.raises(Forbidden):
        await service.assert_child_access(
            caregiver_id=caregiver_id, child_id=child_id, min_role=domain.Role.CO_CAREGIVER
        )
    await service.assert_child_access(
        caregiver_id=caregiver_id, child_id=child_id, min_role=domain.Role.THERAPIST
    )


# ============================================================================
# Play PIN
# ============================================================================


async def test_the_pin_locks_after_five_wrong_attempts_and_the_account_still_works(
    service: IdentityService, repo: FakeRepo
) -> None:
    caregiver = FakeCaregiver(id=uuid.uuid4(), phone_e164=PHONE)
    repo.caregivers[caregiver.id] = caregiver
    await service.set_play_pin(caregiver_id=caregiver.id, pin="1234")

    assert await service.verify_play_pin(caregiver_id=caregiver.id, pin="1234") is True

    for _ in range(domain.PLAY_PIN_MAX_ATTEMPTS - 1):
        assert await service.verify_play_pin(caregiver_id=caregiver.id, pin="9999") is False

    with pytest.raises(PinLocked):
        await service.verify_play_pin(caregiver_id=caregiver.id, pin="9999")
    # And it stays locked, even for the correct PIN.
    with pytest.raises(PinLocked):
        await service.verify_play_pin(caregiver_id=caregiver.id, pin="1234")

    # The PIN never protects data — the caregiver's account is the escape hatch.
    assert repo.caregivers[caregiver.id].play_pin_hash is not None


async def test_a_correct_pin_clears_the_failure_counter(
    service: IdentityService, repo: FakeRepo
) -> None:
    caregiver = FakeCaregiver(id=uuid.uuid4(), phone_e164=PHONE)
    repo.caregivers[caregiver.id] = caregiver
    await service.set_play_pin(caregiver_id=caregiver.id, pin="1234")

    for _ in range(3):
        await service.verify_play_pin(caregiver_id=caregiver.id, pin="0000")
    assert repo.pins[caregiver.id].failed_attempts == 3

    await service.verify_play_pin(caregiver_id=caregiver.id, pin="1234")
    assert repo.pins[caregiver.id].failed_attempts == 0


async def test_a_non_numeric_pin_is_refused(service: IdentityService, repo: FakeRepo) -> None:
    caregiver = FakeCaregiver(id=uuid.uuid4(), phone_e164=PHONE)
    repo.caregivers[caregiver.id] = caregiver
    for bad in ("123", "12345", "abcd", ""):
        with pytest.raises(InvalidCredentials):
            await service.set_play_pin(caregiver_id=caregiver.id, pin=bad)


async def test_verifying_a_pin_that_was_never_set_is_a_clean_404(
    service: IdentityService, repo: FakeRepo
) -> None:
    from app.core.errors import NotFound

    caregiver = FakeCaregiver(id=uuid.uuid4(), phone_e164=PHONE)
    repo.caregivers[caregiver.id] = caregiver
    with pytest.raises(NotFound):
        await service.verify_play_pin(caregiver_id=caregiver.id, pin="1234")
    with pytest.raises(NotFound):
        await service.verify_play_pin(caregiver_id=uuid.uuid4(), pin="1234")


def test_the_pin_hash_is_argon2_and_not_the_pin() -> None:
    from app.modules.identity.security import hash_secret, verify_secret

    hashed = hash_secret("1234")
    assert "1234" not in hashed
    assert hashed.startswith("$argon2")
    assert verify_secret("1234", hashed)
    assert not verify_secret("9999", hashed)


def test_verify_secret_returns_false_on_a_malformed_hash() -> None:
    """A corrupt hash is a failed verify, not a 500."""
    from app.modules.identity.security import verify_secret

    assert not verify_secret("1234", "not-a-hash")
    assert not verify_secret("1234", "")


# ============================================================================
# The log-leak assertion
# ============================================================================


async def test_no_secret_appears_in_logs_during_a_full_auth_flow(
    service: IdentityService, repo: FakeRepo, sms: NullSms
) -> None:
    """P01: 'assert by capturing log output during the full auth flow and
    grepping'. Captured at DEBUG, which is the worst case.
    """
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    root = logging.getLogger()
    previous_level = root.level
    configure_logging(level="DEBUG", service="sanad-api")
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        await service.request_otp(phone_e164=PHONE, client_ip="1.1.1.1")
        code = _code_from(sms)
        tokens = await service.verify_otp(
            phone_e164=PHONE, code=code, client_ip="1.1.1.1", user_agent="agent"
        )
        rotated = await service.refresh(refresh_token=tokens.refresh_token, user_agent="agent")
        # A failed attempt too — the error path logs more than the happy one.
        await service.request_otp(phone_e164=PHONE, client_ip="1.1.1.1")
        with pytest.raises(InvalidCredentials):
            await service.verify_otp(
                phone_e164=PHONE, code="000000", client_ip="1.1.1.1", user_agent="agent"
            )
        with pytest.raises(RefreshReuseDetected):
            await service.refresh(refresh_token=tokens.refresh_token, user_agent="agent")
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)

    logs = buffer.getvalue()
    assert logs, "nothing was logged — the test would pass vacuously"

    secrets = {
        "otp code": code,
        "refresh token": tokens.refresh_token,
        "rotated refresh token": rotated.refresh_token,
        "access token": tokens.access_token,
        "otp code hash": repo.otps[0].code_hash,
        "refresh token hash": domain.hash_refresh_token(tokens.refresh_token),
        "phone number": PHONE,
    }
    leaked = {name: value for name, value in secrets.items() if value and value in logs}
    assert leaked == {}, f"these appeared in DEBUG logs: {sorted(leaked)}"

    # And every line is still structured JSON, so the allow-list actually ran.
    for line in logs.strip().splitlines():
        record = json.loads(line)
        assert "event" in record


async def test_the_log_leak_test_would_catch_a_real_leak(sms: NullSms) -> None:
    """Guard against the previous test passing because nothing is logged."""
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    root = logging.getLogger()
    configure_logging(level="DEBUG", service="sanad-api")
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        # `event` is on the allow-list, so a code smuggled into the message
        # itself WOULD survive. That is the leak shape the assertion must catch.
        structlog.get_logger("t").info("otp_code_483920_leaked")
    finally:
        root.removeHandler(handler)
    assert "483920" in buffer.getvalue()
