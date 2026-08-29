"""FastAPI dependencies for authentication and authorisation.

`require_child_access` is the single most important function in this file. Every
route whose path contains `{child_id}` must depend on it, and
`tools/guards/route_authorisation.py` fails the build if one does not. A missing
check here is an IDOR against a child's clinical record — the happy path works
perfectly, so no ordinary test catches it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Annotated, Any
from uuid import UUID

import jwt
from fastapi import Depends, Path, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.core.errors import Unauthorised
from app.core.redis import get_redis
from app.modules.identity.domain import Role
from app.modules.identity.ratelimit import RateLimiter
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.security import decode_access_token
from app.modules.identity.service import IdentityService
from app.modules.identity.sms import SmsProvider, build_sms_provider

#: Overridable in tests so a NullSms instance can be inspected.
_sms_override: SmsProvider | None = None


def set_sms_provider(provider: SmsProvider | None) -> None:
    global _sms_override
    _sms_override = provider


async def get_identity_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AsyncIterator[IdentityService]:
    settings = get_settings()
    redis: Redis = get_redis()
    yield IdentityService(
        repo=IdentityRepository(session),
        limiter=RateLimiter(redis),
        sms=_sms_override or build_sms_provider(settings),
        settings=settings,
    )


def _bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise Unauthorised(detail="Missing bearer token.")
    return token


async def current_caregiver_id(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> UUID:
    """Decode the access token. 401 on anything wrong, never 500."""
    token = _bearer_token(request)
    try:
        claims = decode_access_token(token, settings)
    except jwt.PyJWTError as exc:
        raise Unauthorised(detail="Invalid or expired token.") from exc
    try:
        return UUID(str(claims["sub"]))
    except (KeyError, ValueError) as exc:
        raise Unauthorised(detail="Token is missing a usable subject.") from exc


CurrentCaregiver = Annotated[UUID, Depends(current_caregiver_id)]
IdentityServiceDep = Annotated[IdentityService, Depends(get_identity_service)]


def require_child_access(
    min_role: Role = Role.CO_CAREGIVER,
) -> Callable[..., Coroutine[Any, Any, Role]]:
    """Build a dependency asserting access to the `{child_id}` path parameter.

    Default is CO_CAREGIVER: read and normal use. Pass `Role.OWNER` for actions
    only an owner may take (consent withdrawal, erasure, transferring ownership).
    A therapist ranks below co-caregiver and so is refused by the default — they
    must be granted explicitly by a route that passes `Role.THERAPIST`.
    """

    async def dependency(
        child_id: Annotated[UUID, Path()],
        caregiver_id: CurrentCaregiver,
        service: IdentityServiceDep,
    ) -> Role:
        return await service.assert_child_access(
            caregiver_id=caregiver_id, child_id=child_id, min_role=min_role
        )

    return dependency


#: The common case, pre-built so routes read cleanly.
ChildAccess = Annotated[Role, Depends(require_child_access())]
OwnerAccess = Annotated[Role, Depends(require_child_access(Role.OWNER))]
