"""Auth and profile routes.

`/auth/otp/request` returns 202 unconditionally. It does not tell the caller
whether the number is registered, whether SMS actually went out, or whether the
number is even routable — all three would be enumeration oracles.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.core.errors import NotFound
from app.modules.identity.deps import CurrentCaregiver, IdentityServiceDep
from app.modules.identity.domain import REFRESH_TOKEN_TTL
from app.modules.identity.schemas import (
    CaregiverChildLink,
    MePatch,
    MeResponse,
    OtpRequest,
    OtpVerify,
    PlayPinSet,
    PlayPinVerifyResponse,
    TokenResponse,
)
from app.modules.identity.service import InvalidCredentials

router = APIRouter(tags=["auth"])

REFRESH_COOKIE = "sanad_refresh"


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _set_refresh_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=int(REFRESH_TOKEN_TTL.total_seconds()),
        httponly=True,
        # Secure is off only outside production, because localhost is http and a
        # Secure cookie would simply never be sent.
        secure=settings.is_production,
        samesite="lax",
        path="/auth",
    )


@router.post("/auth/otp/request", status_code=status.HTTP_202_ACCEPTED)
async def request_otp(
    payload: OtpRequest,
    request: Request,
    service: IdentityServiceDep,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    await service.request_otp(phone_e164=payload.phone_e164, client_ip=_client_ip(request))
    await session.commit()
    # Applied on every path, including the successful one, so that timing carries
    # no information about whether the number exists.
    await service.enumeration_jitter()
    return {}


@router.get("/auth/otp/latest", tags=["auth"], include_in_schema=False)
async def latest_dev_otp(
    phone_e164: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, str]:
    """The last code the NULL provider "sent". Development and CI only.

    ============================================================================
    THIS ROUTE MUST NOT EXIST IN PRODUCTION, AND IT DOES NOT
    ============================================================================
    Two conditions gate it, and either one absent is a 404:

      * `SANAD_ENVIRONMENT` is not `production`;
      * the configured SMS provider is the null one, which never sends
        anything to a phone.

    So the only codes it can ever return are codes that were never delivered.
    It exists because the alternative for an automated end-to-end test is a
    hard-coded OTP or a bypassed sign-in, and both of those are back doors that
    ship. This one cannot ship: `include_in_schema=False` keeps it out of the
    generated client, and the two gates keep it out of any deployment.
    ============================================================================
    """
    from app.modules.identity.sms import LAST_DEV_CODES

    if settings.is_production or settings.sms_provider not in ("", "null", None):
        raise NotFound(detail="Not found.")
    code = LAST_DEV_CODES.get(phone_e164)
    if code is None:
        raise NotFound(detail="No code has been requested for that number.")
    return {"code": code}


@router.post("/auth/otp/verify")
async def verify_otp(
    payload: OtpVerify,
    request: Request,
    response: Response,
    service: IdentityServiceDep,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    tokens = await service.verify_otp(
        phone_e164=payload.phone_e164,
        code=payload.code,
        client_ip=_client_ip(request),
        user_agent=request.headers.get("User-Agent"),
    )
    await session.commit()
    _set_refresh_cookie(response, tokens.refresh_token, settings)
    return TokenResponse(
        access_token=tokens.access_token,
        expires_in=tokens.expires_in,
        is_new_user=tokens.is_new_user,
    )


@router.post("/auth/refresh")
async def refresh(
    request: Request,
    response: Response,
    service: IdentityServiceDep,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise InvalidCredentials(detail="No refresh cookie present.")
    try:
        tokens = await service.refresh(
            refresh_token=token, user_agent=request.headers.get("User-Agent")
        )
    except Exception:
        # A reuse detection revokes a whole family; that write must survive the
        # error response, or a stolen token stays live.
        await session.commit()
        raise
    await session.commit()
    _set_refresh_cookie(response, tokens.refresh_token, settings)
    return TokenResponse(access_token=tokens.access_token, expires_in=tokens.expires_in)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    service: IdentityServiceDep,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    await service.logout(refresh_token=request.cookies.get(REFRESH_COOKIE))
    await session.commit()
    response.delete_cookie(REFRESH_COOKIE, path="/auth")


@router.get("/me", tags=["me"])
async def read_me(
    caregiver_id: CurrentCaregiver,
    service: IdentityServiceDep,
) -> MeResponse:
    caregiver = await service.get_caregiver_or_404(caregiver_id)
    links = await service.repo.list_links_with_names(caregiver_id)
    return MeResponse(
        id=caregiver.id,
        display_name=caregiver.display_name,
        phone_e164=caregiver.phone_e164,
        email=caregiver.email,
        relationship=caregiver.relationship,
        governorate=caregiver.governorate,
        locale=caregiver.locale,
        has_play_pin=caregiver.play_pin_hash is not None,
        children=[
            CaregiverChildLink(id=child_id, display_name=display_name, role=role)
            for child_id, display_name, role in links
        ],
    )


@router.patch("/me", tags=["me"])
async def patch_me(
    payload: MePatch,
    caregiver_id: CurrentCaregiver,
    service: IdentityServiceDep,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MeResponse:
    caregiver = await service.get_caregiver_or_404(caregiver_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(caregiver, field, value)
    await session.commit()
    return await read_me(caregiver_id, service)


@router.put("/me/play-pin", status_code=status.HTTP_204_NO_CONTENT, tags=["me"])
async def set_play_pin(
    payload: PlayPinSet,
    caregiver_id: CurrentCaregiver,
    service: IdentityServiceDep,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    await service.set_play_pin(caregiver_id=caregiver_id, pin=payload.pin)
    await session.commit()


@router.post("/me/play-pin/verify", tags=["me"])
async def verify_play_pin(
    payload: PlayPinSet,
    caregiver_id: CurrentCaregiver,
    service: IdentityServiceDep,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PlayPinVerifyResponse:
    try:
        ok = await service.verify_play_pin(caregiver_id=caregiver_id, pin=payload.pin)
    except Exception:
        # The lockout counter must persist even when the request errors, or the
        # 5-attempt limit is trivially reset by triggering the error path.
        await session.commit()
        raise
    await session.commit()
    return PlayPinVerifyResponse(ok=ok)
