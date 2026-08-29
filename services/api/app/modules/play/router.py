"""Play routes. docs/05 §6.

**Read this before adding a route here.** No path contains `{child_id}`, so
`tools/guards/route_authorisation.py` cannot check these and `ChildAccess`
cannot be declared on them. Every route goes through a `PlayService` method that
resolves `{session_id}` to its child and calls `assert_child_access`. A route
that reaches the repository directly is an IDOR against a child's play history.

`POST /play/sessions/{id}/attempts` and `.../attempts/batch` are the same
handler with a one-or-many body, because they are the same operation: the client
posts one attempt while online and drains a batch after a reconnect, and having
one code path is what makes the second case as well tested as the first.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.modules.children.repository import ChildrenRepository
from app.modules.identity.deps import CurrentCaregiver, IdentityServiceDep
from app.modules.play.repository import PlayRepository
from app.modules.play.schemas import (
    AttemptAccepted,
    AttemptBatch,
    AttemptIn,
    SessionCreated,
    SessionEnd,
    SessionStart,
    SessionSummary,
)
from app.modules.play.service import PlayService
from app.modules.progress.history import ProgressHistory
from app.modules.progress.repository import ProgressRepository
from app.modules.progress.service import ProgressService

router = APIRouter(tags=["play"])


async def get_play_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    identity: IdentityServiceDep,
) -> AsyncIterator[PlayService]:
    yield PlayService(
        repo=PlayRepository(session),
        children=ChildrenRepository(session),
        identity=identity,
        # Constructed here rather than resolved through the progress router's
        # factory: play depends on the rollup path, not on whatever a test has
        # swapped the progress service for.
        progress=ProgressService(
            store=ProgressRepository(session), history=ProgressHistory(session)
        ),
    )


PlayServiceDep = Annotated[PlayService, Depends(get_play_service)]


@router.post("/play/sessions", status_code=status.HTTP_201_CREATED)
async def start_session(
    payload: SessionStart,
    caregiver_id: CurrentCaregiver,
    service: PlayServiceDep,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SessionCreated:
    """Create a session and return the whole plan.

    The full manifest, not the first activity: docs/04e §C13 requires that a
    network drop after the first prompt changes nothing on screen, and a client
    that fetches activity N+1 mid-session cannot honour that.
    """
    created = await service.start(
        child_id=payload.child_id, caregiver_id=caregiver_id, minutes=payload.minutes
    )
    await session.commit()
    return created


@router.post("/play/sessions/{session_id}/attempts", status_code=status.HTTP_202_ACCEPTED)
async def record_attempt(
    session_id: UUID,
    payload: AttemptIn,
    caregiver_id: CurrentCaregiver,
    service: PlayServiceDep,
    session: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AttemptAccepted:
    """One attempt. Re-posting the same idempotency key is a no-op, not a row."""
    if idempotency_key:
        payload = payload.model_copy(update={"idempotency_key": idempotency_key})
    accepted = await service.record_attempts(
        session_id=session_id,
        caregiver_id=caregiver_id,
        batch=AttemptBatch(attempts=[payload]),
    )
    await session.commit()
    return accepted


@router.post("/play/sessions/{session_id}/attempts/batch", status_code=status.HTTP_202_ACCEPTED)
async def record_attempts(
    session_id: UUID,
    payload: AttemptBatch,
    caregiver_id: CurrentCaregiver,
    service: PlayServiceDep,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AttemptAccepted:
    """The outbox drain after a reconnect. Duplicates are counted, not rejected."""
    accepted = await service.record_attempts(
        session_id=session_id, caregiver_id=caregiver_id, batch=payload
    )
    await session.commit()
    return accepted


@router.post("/play/sessions/{session_id}/end")
async def end_session(
    session_id: UUID,
    payload: SessionEnd,
    caregiver_id: CurrentCaregiver,
    service: PlayServiceDep,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SessionSummary:
    """Close the session, write its `session_end` event and rebuild the rollups.

    The rollup runs inline rather than on a worker. It is two queries over one
    child's sessions, and a caregiver who opens the dashboard immediately after
    a session must not see yesterday's numbers.
    """
    summary = await service.end(
        session_id=session_id,
        caregiver_id=caregiver_id,
        reason=payload.reason,
        minutes=payload.minutes,
    )
    await session.commit()
    return summary
