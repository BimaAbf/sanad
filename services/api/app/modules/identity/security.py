"""Password/PIN hashing and JWT signing.

Separated from domain.py because argon2 and JWT are I/O-adjacent (they read
config and consume real time), and domain.py must stay dependency-free.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any
from uuid import UUID, uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import Settings, get_settings
from app.modules.identity.domain import ACCESS_TOKEN_TTL, NBF_LEEWAY

ALGORITHM = "RS256"

#: argon2id at the library defaults, which target ~50 ms. A play PIN has only
#: 10,000 possibilities, so the work factor is doing real work here: it is what
#: makes offline brute force of a stolen hash expensive rather than instant.
_hasher = PasswordHasher()


def hash_secret(value: str) -> str:
    return _hasher.hash(value)


def verify_secret(value: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, value)
    except VerifyMismatchError:
        return False
    except Exception:  # noqa: BLE001 -- a malformed hash is a failed verify, not a 500
        return False


def needs_rehash(hashed: str) -> bool:
    return bool(_hasher.check_needs_rehash(hashed))


@lru_cache(maxsize=1)
def _dev_keypair() -> tuple[str, str]:
    """An ephemeral RS256 keypair for local development and tests.

    Generated in-process and never written to disk, so there is no key file that
    can be accidentally committed or reused in a deployment. Production supplies
    MISK_JWT_PRIVATE_KEY / MISK_JWT_PUBLIC_KEY; `Settings` refuses to start in
    production without them.
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


def _keys(settings: Settings) -> tuple[str, str]:
    if settings.jwt_private_key and settings.jwt_public_key:
        return settings.jwt_private_key, settings.jwt_public_key
    if settings.is_production:  # pragma: no cover -- guarded again in Settings
        raise RuntimeError("MISK_JWT_PRIVATE_KEY and MISK_JWT_PUBLIC_KEY are required")
    return _dev_keypair()


def issue_access_token(
    *,
    caregiver_id: UUID,
    scope: str = "caregiver",
    now: datetime | None = None,
    settings: Settings | None = None,
) -> tuple[str, int]:
    """Return (token, expires_in_seconds).

    Claims are exactly {sub, cgid, jti, scope} plus the standard time claims.
    `nbf` is backdated by NBF_LEEWAY so a device with a slightly fast clock does
    not reject its own freshly-minted token.
    """
    settings = settings or get_settings()
    now = now or datetime.now(UTC)
    private_key, _ = _keys(settings)
    payload: dict[str, Any] = {
        "sub": str(caregiver_id),
        "cgid": str(caregiver_id),
        "jti": str(uuid4()),
        "scope": scope,
        "iat": int(now.timestamp()),
        "nbf": int((now - NBF_LEEWAY).timestamp()),
        "exp": int((now + ACCESS_TOKEN_TTL).timestamp()),
    }
    token = jwt.encode(payload, private_key, algorithm=ALGORITHM)
    return token, int(ACCESS_TOKEN_TTL.total_seconds())


def decode_access_token(token: str, settings: Settings | None = None) -> dict[str, Any]:
    """Decode and verify. Raises jwt.PyJWTError on anything wrong."""
    settings = settings or get_settings()
    _, public_key = _keys(settings)
    decoded: dict[str, Any] = jwt.decode(
        token,
        public_key,
        algorithms=[ALGORITHM],
        leeway=timedelta(seconds=int(NBF_LEEWAY.total_seconds())),
        options={"require": ["exp", "sub", "jti"]},
    )
    return decoded
