"""Pure identity logic. No I/O, no framework, no database.

Everything here is deterministic and total, so it can be property-tested
exhaustively. `domain.py` may import nothing from the project except other
`domain.py` modules — that rule is what keeps this file testable.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

# --- OTP -------------------------------------------------------------------

OTP_DIGITS = 6
OTP_TTL = timedelta(minutes=5)
OTP_MAX_ATTEMPTS = 3

# --- tokens ----------------------------------------------------------------

ACCESS_TOKEN_TTL = timedelta(minutes=15)
REFRESH_TOKEN_TTL = timedelta(days=30)
#: Devices with a skewed clock must not be locked out of their own account.
NBF_LEEWAY = timedelta(seconds=60)

# --- play PIN --------------------------------------------------------------

PLAY_PIN_LENGTH = 4
PLAY_PIN_MAX_ATTEMPTS = 5
PLAY_PIN_LOCKOUT = timedelta(minutes=15)

# --- rate limits (docs/04a §C01) -------------------------------------------

RATE_OTP_PER_PHONE_PER_HOUR = 3
RATE_OTP_PER_IP_PER_HOUR = 10
RATE_VERIFY_PER_IP_PER_HOUR = 10

#: Bounds of the jitter applied to the no-send path of /auth/otp/request, so
#: that "this number exists" and "it does not" are indistinguishable to a
#: caller with a stopwatch.
ENUMERATION_JITTER_MS = (80, 140)


class Role(StrEnum):
    """Mirrors the caregiver_role enum. Ordered least → most privileged."""

    THERAPIST = "therapist"
    CO_CAREGIVER = "co_caregiver"
    OWNER = "owner"


#: Higher value means more privilege. `require_child_access(min_role=...)`
#: compares on this, so a therapist never satisfies an owner-level requirement.
ROLE_RANK: dict[Role, int] = {
    Role.THERAPIST: 1,
    Role.CO_CAREGIVER: 2,
    Role.OWNER: 3,
}


def role_satisfies(actual: Role, minimum: Role) -> bool:
    return ROLE_RANK[actual] >= ROLE_RANK[minimum]


def generate_otp_code() -> str:
    """A cryptographically random 6-digit code, zero-padded.

    `secrets.randbelow` rather than `random`: this value is a credential.
    """
    return f"{secrets.randbelow(10**OTP_DIGITS):0{OTP_DIGITS}d}"


def hash_otp_code(code: str, pepper: str) -> str:
    """sha256(code || pepper).

    A 6-digit code has only a million possibilities, so the hash alone is not
    much protection — the pepper (which lives in config, never in the database)
    is what makes a stolen `auth_otp` table useless. Brute force is bounded by
    OTP_MAX_ATTEMPTS, which is the real defence.
    """
    return hashlib.sha256(f"{code}{pepper}".encode()).hexdigest()


def verify_otp_code(code: str, code_hash: str, pepper: str) -> bool:
    """Constant-time comparison. Never `==` on a credential."""
    return hmac.compare_digest(hash_otp_code(code, pepper), code_hash)


def generate_refresh_token() -> str:
    """Opaque, 256 bits of entropy. Never a JWT: it must be revocable."""
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    """Refresh tokens are stored hashed so a database leak is not a session leak.

    Plain sha256 without a work factor is correct here and wrong for a password:
    the input is 256 bits of uniform entropy, so there is nothing to brute-force.
    """
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class OtpState:
    """Everything needed to decide whether a code may be verified."""

    attempts: int
    consumed_at: datetime | None
    expires_at: datetime


class OtpRejection(StrEnum):
    EXPIRED = "expired"
    CONSUMED = "consumed"
    TOO_MANY_ATTEMPTS = "too_many_attempts"
    WRONG_CODE = "wrong_code"


def check_otp_usable(state: OtpState, now: datetime) -> OtpRejection | None:
    """Why this OTP may not be used, or None if it may.

    Checked before the code is compared, so an expired or exhausted OTP costs
    no comparison and reveals nothing.
    """
    if state.consumed_at is not None:
        return OtpRejection.CONSUMED
    if now >= state.expires_at:
        return OtpRejection.EXPIRED
    if state.attempts >= OTP_MAX_ATTEMPTS:
        return OtpRejection.TOO_MANY_ATTEMPTS
    return None


@dataclass(frozen=True, slots=True)
class PinLockState:
    failed_attempts: int
    locked_until: datetime | None


def is_pin_locked(state: PinLockState, now: datetime) -> bool:
    return state.locked_until is not None and now < state.locked_until


def next_pin_lock_state(state: PinLockState, *, success: bool, now: datetime) -> PinLockState:
    """Advance the lockout counter.

    A success always clears the counter. The fifth consecutive failure locks for
    15 minutes; the caregiver's account credentials remain the escape hatch, so
    this can never strand someone out of their own account (docs/04a §C01).
    """
    if success:
        return PinLockState(failed_attempts=0, locked_until=None)
    attempts = state.failed_attempts + 1
    if attempts >= PLAY_PIN_MAX_ATTEMPTS:
        return PinLockState(failed_attempts=attempts, locked_until=now + PLAY_PIN_LOCKOUT)
    return PinLockState(failed_attempts=attempts, locked_until=None)


def is_valid_play_pin(pin: str) -> bool:
    return len(pin) == PLAY_PIN_LENGTH and pin.isdigit() and pin.isascii()


def access_token_expiry(now: datetime) -> datetime:
    return now + ACCESS_TOKEN_TTL


def refresh_token_expiry(now: datetime) -> datetime:
    return now + REFRESH_TOKEN_TTL


def otp_expiry(now: datetime) -> datetime:
    return now + OTP_TTL


def utcnow() -> datetime:
    return datetime.now(UTC)
