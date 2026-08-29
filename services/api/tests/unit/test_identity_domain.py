"""Identity domain logic. No I/O, so these can be exhaustive."""

from __future__ import annotations

import datetime as dt

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.identity import domain

NOW = dt.datetime(2026, 8, 29, 12, 0, tzinfo=dt.UTC)


# --- OTP codes -------------------------------------------------------------


def test_otp_code_is_always_six_digits() -> None:
    for _ in range(2000):
        code = domain.generate_otp_code()
        assert len(code) == domain.OTP_DIGITS
        assert code.isdigit()


def test_otp_codes_span_the_full_range() -> None:
    """Zero-padding must not collapse the space to 900,000 codes."""
    codes = {domain.generate_otp_code() for _ in range(20000)}
    assert any(c.startswith("0") for c in codes), "leading-zero codes never generated"
    assert len(codes) > 15000, "generator is not close to uniform"


def test_hash_is_stable_and_pepper_dependent() -> None:
    a = domain.hash_otp_code("123456", "pepper-a")
    b = domain.hash_otp_code("123456", "pepper-a")
    c = domain.hash_otp_code("123456", "pepper-b")
    assert a == b
    assert a != c


def test_verify_otp_code_matches_only_the_right_code() -> None:
    hashed = domain.hash_otp_code("483920", "p")
    assert domain.verify_otp_code("483920", hashed, "p")
    assert not domain.verify_otp_code("483921", hashed, "p")
    assert not domain.verify_otp_code("483920", hashed, "wrong-pepper")


def test_plaintext_code_never_appears_in_its_hash() -> None:
    hashed = domain.hash_otp_code("483920", "p")
    assert "483920" not in hashed


# --- OTP state machine -----------------------------------------------------


@pytest.mark.parametrize(
    ("attempts", "consumed", "expires_delta", "expected"),
    [
        (0, None, dt.timedelta(minutes=1), None),
        (0, NOW, dt.timedelta(minutes=1), domain.OtpRejection.CONSUMED),
        (0, None, dt.timedelta(minutes=-1), domain.OtpRejection.EXPIRED),
        (3, None, dt.timedelta(minutes=1), domain.OtpRejection.TOO_MANY_ATTEMPTS),
        (4, None, dt.timedelta(minutes=1), domain.OtpRejection.TOO_MANY_ATTEMPTS),
        # Consumed beats expired: a used code is used regardless of its clock.
        (0, NOW, dt.timedelta(minutes=-1), domain.OtpRejection.CONSUMED),
    ],
)
def test_check_otp_usable(
    attempts: int,
    consumed: dt.datetime | None,
    expires_delta: dt.timedelta,
    expected: domain.OtpRejection | None,
) -> None:
    state = domain.OtpState(attempts=attempts, consumed_at=consumed, expires_at=NOW + expires_delta)
    assert domain.check_otp_usable(state, NOW) is expected


def test_otp_expires_exactly_at_the_boundary() -> None:
    state = domain.OtpState(attempts=0, consumed_at=None, expires_at=NOW)
    assert domain.check_otp_usable(state, NOW) is domain.OtpRejection.EXPIRED


@given(attempts=st.integers(min_value=0, max_value=50))
def test_attempts_at_or_above_the_cap_always_reject(attempts: int) -> None:
    state = domain.OtpState(
        attempts=attempts, consumed_at=None, expires_at=NOW + dt.timedelta(minutes=1)
    )
    result = domain.check_otp_usable(state, NOW)
    if attempts >= domain.OTP_MAX_ATTEMPTS:
        assert result is domain.OtpRejection.TOO_MANY_ATTEMPTS
    else:
        assert result is None


# --- refresh tokens --------------------------------------------------------


def test_refresh_tokens_are_unique_and_high_entropy() -> None:
    tokens = {domain.generate_refresh_token() for _ in range(5000)}
    assert len(tokens) == 5000
    assert all(len(t) >= 40 for t in tokens)


def test_refresh_hash_is_deterministic_and_hides_the_token() -> None:
    token = domain.generate_refresh_token()
    assert domain.hash_refresh_token(token) == domain.hash_refresh_token(token)
    assert token not in domain.hash_refresh_token(token)


# --- roles -----------------------------------------------------------------


def test_role_ordering() -> None:
    assert domain.role_satisfies(domain.Role.OWNER, domain.Role.CO_CAREGIVER)
    assert domain.role_satisfies(domain.Role.OWNER, domain.Role.OWNER)
    assert not domain.role_satisfies(domain.Role.CO_CAREGIVER, domain.Role.OWNER)
    # A therapist ranks below a co-caregiver, so the default gate refuses them.
    assert not domain.role_satisfies(domain.Role.THERAPIST, domain.Role.CO_CAREGIVER)
    assert domain.role_satisfies(domain.Role.THERAPIST, domain.Role.THERAPIST)


@given(
    actual=st.sampled_from(list(domain.Role)),
    minimum=st.sampled_from(list(domain.Role)),
)
def test_role_satisfies_is_a_total_order(actual: domain.Role, minimum: domain.Role) -> None:
    expected = domain.ROLE_RANK[actual] >= domain.ROLE_RANK[minimum]
    assert domain.role_satisfies(actual, minimum) is expected


# --- play PIN lockout ------------------------------------------------------


def test_pin_locks_on_the_fifth_failure_not_the_fourth() -> None:
    state = domain.PinLockState(failed_attempts=0, locked_until=None)
    for expected_attempts in range(1, domain.PLAY_PIN_MAX_ATTEMPTS):
        state = domain.next_pin_lock_state(state, success=False, now=NOW)
        assert state.failed_attempts == expected_attempts
        assert state.locked_until is None, f"locked early at {expected_attempts}"

    state = domain.next_pin_lock_state(state, success=False, now=NOW)
    assert state.failed_attempts == domain.PLAY_PIN_MAX_ATTEMPTS
    assert state.locked_until == NOW + domain.PLAY_PIN_LOCKOUT
    assert domain.is_pin_locked(state, NOW)


def test_lock_expires_after_the_window() -> None:
    state = domain.PinLockState(failed_attempts=5, locked_until=NOW + domain.PLAY_PIN_LOCKOUT)
    assert domain.is_pin_locked(state, NOW)
    assert not domain.is_pin_locked(state, NOW + domain.PLAY_PIN_LOCKOUT)


def test_success_clears_the_counter() -> None:
    state = domain.PinLockState(failed_attempts=4, locked_until=None)
    cleared = domain.next_pin_lock_state(state, success=True, now=NOW)
    assert cleared.failed_attempts == 0
    assert cleared.locked_until is None


@settings(max_examples=200)
@given(results=st.lists(st.booleans(), min_size=1, max_size=40))
def test_a_success_anywhere_always_leaves_an_unlocked_state(results: list[bool]) -> None:
    """However many failures precede it, one success must restore access."""
    state = domain.PinLockState(failed_attempts=0, locked_until=None)
    for result in results:
        state = domain.next_pin_lock_state(state, success=result, now=NOW)
    if results[-1]:
        assert not domain.is_pin_locked(state, NOW)


@pytest.mark.parametrize(
    ("pin", "valid"),
    [
        ("1234", True),
        ("0000", True),
        ("123", False),
        ("12345", False),
        ("12a4", False),
        ("", False),
        ("١٢٣٤", False),  # Arabic-Indic digits: str.isdigit() is True, isascii() is not
    ],
)
def test_play_pin_validation(pin: str, valid: bool) -> None:
    assert domain.is_valid_play_pin(pin) is valid


# --- expiries --------------------------------------------------------------


def test_token_and_otp_lifetimes_match_the_spec() -> None:
    assert domain.access_token_expiry(NOW) == NOW + dt.timedelta(minutes=15)
    assert domain.refresh_token_expiry(NOW) == NOW + dt.timedelta(days=30)
    assert domain.otp_expiry(NOW) == NOW + dt.timedelta(minutes=5)
    assert dt.timedelta(seconds=60) == domain.NBF_LEEWAY


def test_rate_limits_match_the_spec() -> None:
    assert domain.RATE_OTP_PER_PHONE_PER_HOUR == 3
    assert domain.RATE_OTP_PER_IP_PER_HOUR == 10
    assert domain.RATE_VERIFY_PER_IP_PER_HOUR == 10
    assert domain.ENUMERATION_JITTER_MS == (80, 140)
