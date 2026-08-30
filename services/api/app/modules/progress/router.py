"""Progress routes. docs/05 §5.

All aggregation is server-side: the client receives render-ready data. That is
not a performance decision — it is what keeps the three product rules in
`domain/views.py` in one place instead of in every client that ever ships.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import AsyncIterator, Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import ServiceUnavailable
from app.modules.identity.deps import ChildAccess, CurrentCaregiver
from app.modules.progress.schemas import (
    AssessmentSummary,
    EventBatch,
    EventBatchAccepted,
    JourneyResponse,
    SkillsResponse,
    TodayResponse,
)
from app.modules.progress.service import ProgressService

router = APIRouter(tags=["progress"])

ProgressServiceFactory = Callable[[AsyncSession], ProgressService]

_service_factory: ProgressServiceFactory | None = None


def set_progress_service_factory(factory: ProgressServiceFactory | None) -> None:
    global _service_factory
    _service_factory = factory


async def get_progress_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AsyncIterator[ProgressService]:
    if _service_factory is None:
        raise ServiceUnavailable(detail="Progress service is not configured.")
    yield _service_factory(session)


@router.post("/events", status_code=status.HTTP_202_ACCEPTED)
async def ingest_events(
    body: EventBatch,
    caregiver_id: CurrentCaregiver,
    service: Annotated[ProgressService, Depends(get_progress_service)],
) -> EventBatchAccepted:
    """Batch ingestion from the client outbox.

    202, always: the client must never wait on analytics, and a child's session
    must never stall because a telemetry write was slow.
    """
    accepted = await service.ingest(caregiver_id=caregiver_id, batch=body)
    return EventBatchAccepted(accepted=accepted, duplicates=len(body.events) - accepted)


@router.get("/children/{child_id}/progress/today")
async def progress_today(
    child_id: UUID,
    _access: ChildAccess,
    service: Annotated[ProgressService, Depends(get_progress_service)],
) -> TodayResponse:
    return await service.today(str(child_id), today=dt.datetime.now(dt.UTC))


@router.get("/children/{child_id}/progress/skills")
async def progress_skills(
    child_id: UUID,
    _access: ChildAccess,
    service: Annotated[ProgressService, Depends(get_progress_service)],
) -> SkillsResponse:
    return await service.skills(str(child_id))


@router.get("/children/{child_id}/progress/journey")
async def progress_journey(
    child_id: UUID,
    _access: ChildAccess,
    service: Annotated[ProgressService, Depends(get_progress_service)],
) -> JourneyResponse:
    """Longitudinal view. Returns `insufficient_data` under three assessments."""
    return await service.journey(str(child_id))


@router.get("/children/{child_id}/progress/assessments")
async def progress_assessments(
    child_id: UUID,
    _access: ChildAccess,
    service: Annotated[ProgressService, Depends(get_progress_service)],
) -> list[AssessmentSummary]:
    return await service.assessments(str(child_id))
