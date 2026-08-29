"""Child and consent routes.

Every route whose path contains `{child_id}` declares `require_child_access`.
`tools/guards/route_authorisation.py` fails the build if one does not.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import AsyncIterator
from email.utils import parsedate_to_datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.core.errors import BadRequest
from app.core.redis import get_redis
from app.modules.children import domain
from app.modules.children.consent_gate import ConsentGate
from app.modules.children.models import Child
from app.modules.children.repository import ChildrenRepository
from app.modules.children.schemas import (
    ChildCreate,
    ChildCreated,
    ChildPatch,
    ChildResponse,
    ConsentChange,
    ConsentItem,
    ConsentList,
    InviteCreate,
    InviteCreated,
    JobAccepted,
)
from app.modules.children.service import ChildrenService
from app.modules.identity.deps import ChildAccess, CurrentCaregiver, OwnerAccess
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.schemas import normalise_phone

router = APIRouter(tags=["children"])


async def get_children_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[ChildrenService]:
    redis: Redis | None
    try:
        redis = get_redis()
    except RuntimeError:
        # Unit tests construct the app without a lifespan; the gate falls back to
        # reading Postgres directly, which is the correct fail-closed behaviour.
        redis = None
    yield ChildrenService(
        repo=ChildrenRepository(session),
        identity_repo=IdentityRepository(session),
        gate=ConsentGate(session, redis),
        settings=settings,
    )


ChildrenServiceDep = Annotated[ChildrenService, Depends(get_children_service)]


def _to_response(child: Child) -> ChildResponse:
    age = domain.age_months(child.date_of_birth, domain.today(), child.gestational_weeks)
    return ChildResponse(
        id=child.id,
        display_name=child.display_name,
        name_vowelised=child.name_vowelised,
        date_of_birth=child.date_of_birth,
        sex=str(child.sex),
        gestational_weeks=child.gestational_weeks,
        comms_level=str(child.comms_level),
        chronological_months=round(age.chronological_months, 2),
        corrected_months=round(age.corrected_months, 2),
        wait_time_ms=child.wait_time_ms,
        max_choices=child.max_choices,
        audio_rate_pct=child.audio_rate_pct,
        calm_mode=child.calm_mode,
        session_minutes=child.session_minutes,
        hearing_aid=child.hearing_aid,
        glasses=child.glasses,
        updated_at=child.updated_at,
    )


@router.post("/children", status_code=status.HTTP_201_CREATED)
async def create_child(
    payload: ChildCreate,
    request: Request,
    caregiver_id: CurrentCaregiver,
    service: ChildrenServiceDep,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChildCreated:
    created = await service.create_child(
        payload=payload,
        caregiver_id=caregiver_id,
        source_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    await session.commit()
    return ChildCreated(
        id=created.child.id,
        chronological_months=round(created.age.chronological_months, 2),
        corrected_months=round(created.age.corrected_months, 2),
    )


@router.get("/children/{child_id}")
async def read_child(
    child_id: UUID,
    _access: ChildAccess,
    service: ChildrenServiceDep,
    response: Response,
) -> ChildResponse:
    child = await service.get_child_or_404(child_id)
    # Echoed so a client can send it straight back as If-Unmodified-Since.
    response.headers["Last-Modified"] = child.updated_at.strftime("%a, %d %b %Y %H:%M:%S GMT")
    return _to_response(child)


@router.patch("/children/{child_id}")
async def patch_child(
    child_id: UUID,
    payload: ChildPatch,
    _access: ChildAccess,
    service: ChildrenServiceDep,
    session: Annotated[AsyncSession, Depends(get_session)],
    if_unmodified_since: Annotated[str | None, Header()] = None,
) -> ChildResponse:
    since: dt.datetime | None = None
    if if_unmodified_since:
        try:
            since = parsedate_to_datetime(if_unmodified_since)
        except (TypeError, ValueError) as exc:
            raise BadRequest(detail="If-Unmodified-Since is not a valid HTTP date.") from exc
        if since.tzinfo is None:
            since = since.replace(tzinfo=dt.UTC)

    changes = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    child = await service.patch_child(child_id=child_id, changes=changes, if_unmodified_since=since)
    await session.commit()
    return _to_response(child)


@router.get("/children/{child_id}/consents")
async def list_consents(
    child_id: UUID,
    _access: ChildAccess,
    service: ChildrenServiceDep,
) -> ConsentList:
    definitions = await service.repo.list_consent_definitions()
    current = await service.repo.current_consents(child_id)
    items = []
    for definition in definitions:
        record = current.get(definition.key)
        items.append(
            ConsentItem(
                key=definition.key,
                version=definition.version,
                status=str(record.status) if record else "withdrawn",
                text_ar=definition.text_ar,
                is_mandatory=definition.is_mandatory,
                granted_at=record.granted_at if record else None,
            )
        )
    return ConsentList(items=items)


@router.post("/children/{child_id}/consents")
async def set_consent(
    child_id: UUID,
    payload: ConsentChange,
    request: Request,
    caregiver_id: CurrentCaregiver,
    # Consent is an owner-level act: a co-caregiver must not be able to withdraw
    # the legal basis for processing another family member's child's data.
    _access: OwnerAccess,
    service: ChildrenServiceDep,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ConsentList:
    await service.set_consent(
        child_id=child_id,
        caregiver_id=caregiver_id,
        key=payload.key,
        granted=payload.granted,
        source_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    await session.commit()
    # Invalidated again after commit: the pre-commit bust closes the same-request
    # window, this one closes the window between commit and the next reader.
    await service.gate.invalidate(str(child_id))
    return await list_consents(child_id, _access, service)


@router.post("/children/{child_id}/invites", status_code=status.HTTP_201_CREATED)
async def create_invite(
    child_id: UUID,
    payload: InviteCreate,
    caregiver_id: CurrentCaregiver,
    _access: OwnerAccess,
    service: ChildrenServiceDep,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> InviteCreated:
    token, expires_at = await service.create_invite(
        child_id=child_id,
        invited_by=caregiver_id,
        phone_e164=normalise_phone(payload.phone_e164),
        role=payload.role,
    )
    await session.commit()
    return InviteCreated(invite_url=f"/invites/{token}/accept", expires_at=expires_at)


@router.post("/invites/{token}/accept")
async def accept_invite(
    token: str,
    caregiver_id: CurrentCaregiver,
    service: ChildrenServiceDep,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    child_id = await service.accept_invite(token=token, caregiver_id=caregiver_id)
    await session.commit()
    return {"child_id": str(child_id)}


@router.post("/children/{child_id}/export", status_code=status.HTTP_202_ACCEPTED)
async def export_child(
    child_id: UUID,
    _access: OwnerAccess,
) -> JobAccepted:
    # TODO(P10): enqueue export_child_data via ARQ. The worker pool lands with
    # the progress module; until then this records the request shape only.
    return JobAccepted(job_id=uuid4())


@router.delete("/children/{child_id}", status_code=status.HTTP_202_ACCEPTED)
async def delete_child(
    child_id: UUID,
    _access: OwnerAccess,
    service: ChildrenServiceDep,
    session: Annotated[AsyncSession, Depends(get_session)],
    erase: Annotated[bool, Query()] = False,
) -> JobAccepted:
    if not erase:
        await service.repo.archive_child(child_id, dt.datetime.now(dt.UTC))
        await session.commit()
        return JobAccepted(job_id=uuid4())
    # TODO(P10): enqueue erase_child (hard delete + cascade + S3 + pgvector +
    # audit tombstone + rollup anonymisation).
    return JobAccepted(job_id=uuid4())
