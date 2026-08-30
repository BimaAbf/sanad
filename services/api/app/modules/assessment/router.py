"""Assessment routes. docs/05 §4.

**Read this before adding a route here.** None of these paths contains
`{child_id}`, so `tools/guards/route_authorisation.py` will not check them and
`ChildAccess` cannot be declared on them. Authorisation happens inside
`AssessmentService`, which resolves `{assessment_id}` to its child and calls
`assert_child_access`. Every new route must go through a service method that
does the same; a route that touches the repository directly is an IDOR.

`POST /assessments/{id}/answers` takes `Idempotency-Key` as a header, matching
the table in docs/05 §1, and falls back to the body field so the offline outbox
-- which stores a body, not headers -- can drain through the same route.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.modules.assessment.repository import AssessmentRepository
from app.modules.assessment.schemas import (
    AnswerIn,
    AssessmentScored,
    AssessmentStart,
    AssessmentState,
)
from app.modules.assessment.service import AssessmentService
from app.modules.children.repository import ChildrenRepository
from app.modules.identity.deps import CurrentCaregiver, IdentityServiceDep

router = APIRouter(tags=["assessment"])


async def get_assessment_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    identity: IdentityServiceDep,
) -> AsyncIterator[AssessmentService]:
    yield AssessmentService(
        repo=AssessmentRepository(session),
        children=ChildrenRepository(session),
        identity=identity,
    )


AssessmentServiceDep = Annotated[AssessmentService, Depends(get_assessment_service)]


@router.post("/assessments", status_code=status.HTTP_201_CREATED)
async def start_assessment(
    payload: AssessmentStart,
    caregiver_id: CurrentCaregiver,
    service: AssessmentServiceDep,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AssessmentState:
    """Start, or resume the one already open for this child."""
    state = await service.start(child_id=payload.child_id, caregiver_id=caregiver_id)
    await session.commit()
    return state


@router.get("/assessments/{assessment_id}")
async def read_assessment(
    assessment_id: UUID,
    caregiver_id: CurrentCaregiver,
    service: AssessmentServiceDep,
) -> AssessmentState:
    """Current state, for resume after a closed tab or a dropped connection."""
    return await service.state(assessment_id=assessment_id, caregiver_id=caregiver_id)


@router.post("/assessments/{assessment_id}/answers")
async def record_answer(
    assessment_id: UUID,
    payload: AnswerIn,
    caregiver_id: CurrentCaregiver,
    service: AssessmentServiceDep,
    session: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AssessmentState:
    """Record one answer plus everything it implies, and return what to ask next.

    Answering an item twice is a correction, not a duplicate: the earlier row is
    superseded and the assessment replays. Re-POSTing the SAME `Idempotency-Key`
    is a no-op, which is what makes a retry after a timeout safe.
    """
    state = await service.answer(
        assessment_id=assessment_id,
        caregiver_id=caregiver_id,
        item_id=payload.item_id,
        verdict=payload.verdict,
        source=payload.source,
        idempotency_key=idempotency_key or payload.idempotency_key,
    )
    await session.commit()
    return state


@router.post("/assessments/{assessment_id}/finalise")
async def finalise_assessment(
    assessment_id: UUID,
    caregiver_id: CurrentCaregiver,
    service: AssessmentServiceDep,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AssessmentScored:
    """Score every domain and close the assessment. Safe to call twice.

    Synchronous rather than the 202 + job in docs/05 §4: scoring is pure
    arithmetic over an answer log that is already in memory. A job queue would
    add a failure mode without removing any work.
    """
    scored = await service.finalise(assessment_id=assessment_id, caregiver_id=caregiver_id)
    await session.commit()
    return scored
