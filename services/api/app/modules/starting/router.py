"""Starting-assessment routes.

**Read this before adding a route here.** Only
`/children/{child_id}/starting-assessment` carries a `{child_id}`, so it
declares `ChildAccess` and `tools/guards/route_authorisation.py` checks it. The
rest are keyed by `{assessment_id}`, which the guard cannot see, so
`StartingService` resolves the assessment to its child and calls
`assert_child_access` in the first statement of every method — the same
arrangement `assessment/router.py` documents.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import NotFound
from app.modules.children.repository import ChildrenRepository
from app.modules.identity.deps import ChildAccess, CurrentCaregiver, IdentityServiceDep
from app.modules.starting.repository import StartingRepository
from app.modules.starting.schemas import (
    AnswerIn,
    StartingResult,
    StartingStart,
    StartingState,
    StartingSummary,
)
from app.modules.starting.service import StartingService
from app.modules.tutor.repository import TutorRepository

router = APIRouter(tags=["starting-assessment"])


async def get_starting_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    identity: IdentityServiceDep,
) -> AsyncIterator[StartingService]:
    yield StartingService(
        repo=StartingRepository(session),
        children=ChildrenRepository(session),
        identity=identity,
        profiles=TutorRepository(session),
    )


StartingServiceDep = Annotated[StartingService, Depends(get_starting_service)]


@router.post("/starting-assessments", status_code=status.HTTP_201_CREATED)
async def start(
    payload: StartingStart,
    caregiver_id: CurrentCaregiver,
    service: StartingServiceDep,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StartingState:
    """Start, or resume the one already open for this child."""
    state = await service.start(child_id=payload.child_id, caregiver_id=caregiver_id)
    await session.commit()
    return StartingState(**state)


@router.get("/starting-assessments/{assessment_id}")
async def read(
    assessment_id: UUID,
    caregiver_id: CurrentCaregiver,
    service: StartingServiceDep,
) -> StartingState:
    """Current state, for resume after a closed tab or a dropped connection."""
    return StartingState(
        **await service.state(assessment_id=assessment_id, caregiver_id=caregiver_id)
    )


@router.post("/starting-assessments/{assessment_id}/answers")
async def answer(
    assessment_id: UUID,
    payload: AnswerIn,
    caregiver_id: CurrentCaregiver,
    service: StartingServiceDep,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StartingState:
    """One answer. Answering the same question twice is a correction.

    Idempotent by construction rather than by a key: the answer log is a JSON
    object keyed by question id, so the same answer posted twice leaves the same
    object. A retry after a timeout cannot create a second answer.
    """
    state = await service.answer(
        assessment_id=assessment_id,
        caregiver_id=caregiver_id,
        question_id=payload.question_id,
        answer_id=payload.answer_id,
    )
    await session.commit()
    return StartingState(**state)


@router.post("/starting-assessments/{assessment_id}/finalise")
async def finalise(
    assessment_id: UUID,
    caregiver_id: CurrentCaregiver,
    service: StartingServiceDep,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StartingResult:
    """Derive the profile and create the initial learner state. Safe to repeat.

    This is the step that makes the assessment matter: it writes `skill_states`
    rows carrying this child's own BKT priors, and a `learner_profiles` row with
    the support and duration the caregiver described. The tutor loop's first
    decision reads both.
    """
    result = await service.finalise(assessment_id=assessment_id, caregiver_id=caregiver_id)
    await session.commit()
    return StartingResult(**result)


@router.get("/children/{child_id}/starting-assessment")
async def latest(
    child_id: UUID,
    _access: ChildAccess,
    caregiver_id: CurrentCaregiver,
    service: StartingServiceDep,
) -> StartingSummary:
    """This child's starting point, for the profile page. 404 when there is none."""
    summary = await service.latest(child_id=child_id, caregiver_id=caregiver_id)
    if summary is None:
        raise NotFound(detail="This child has no starting assessment yet.")
    return StartingSummary(**summary)


__all__ = ["router"]
