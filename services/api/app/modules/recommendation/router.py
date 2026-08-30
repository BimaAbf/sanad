"""Recommendation routes.

Every path here carries `{child_id}` and therefore declares `ChildAccess`, which
`tools/guards/route_authorisation.py` checks mechanically. That is not a
formality on this module in particular: the response to
`GET /children/{id}/recommendation` is derived from that child's entire attempt
history, and the memory-search route returns sentences describing it directly.

The service is resolved through a module-level factory, the same seam
`progress` and `voice` use, so `app/core/wiring.py` stays the one place that
knows what production wires in and a test can drive these routes with no
database.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import NotFound, ServiceUnavailable
from app.modules.identity.deps import ChildAccess
from app.modules.recommendation.schemas import (
    MemoryHit,
    MemorySearchRequest,
    MemorySearchResponse,
    NextExerciseResponse,
    ReindexResponse,
)
from app.modules.recommendation.service import RecommendationService, documents_as_rows

router = APIRouter(tags=["recommendation"])

RecommendationServiceFactory = Callable[[AsyncSession], RecommendationService]

_service_factory: RecommendationServiceFactory | None = None


def set_recommendation_service_factory(
    factory: RecommendationServiceFactory | None,
) -> None:
    global _service_factory
    _service_factory = factory


async def get_recommendation_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AsyncIterator[RecommendationService]:
    if _service_factory is None:
        raise ServiceUnavailable(detail="Recommendation service is not configured.")
    yield _service_factory(session)


RecommendationServiceDep = Annotated[RecommendationService, Depends(get_recommendation_service)]


@router.get("/children/{child_id}/recommendation", response_model=NextExerciseResponse)
async def next_exercise(
    child_id: UUID,
    _access: ChildAccess,
    service: RecommendationServiceDep,
) -> NextExerciseResponse:
    """The next best exercise for this child.

    404 rather than an empty 200 when there is nothing to recommend. An empty
    recommendation object would have to carry a label, and the only honest label
    is an empty string -- which the caregiver app would render as a blank card.
    """
    recommendation = await service.next_exercise(str(child_id))
    if recommendation is None:
        raise NotFound(detail="No eligible activity for this child yet.")
    return NextExerciseResponse(
        activity_code=f"listen_point:{recommendation.skill_code}",
        skill_id=recommendation.skill_id,
        skill_code=recommendation.skill_code,
        label_ar=recommendation.label_ar,
        kind=recommendation.kind,
        reason_ar=recommendation.reason_ar,
        source=recommendation.source,
        plan=list(recommendation.ordered_skill_ids),
        grounded_in=list(recommendation.grounded_in),
    )


@router.post(
    "/children/{child_id}/recommendation/reindex",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ReindexResponse,
)
async def reindex(
    child_id: UUID,
    _access: ChildAccess,
    service: RecommendationServiceDep,
) -> ReindexResponse:
    """Rebuild this child's retrieval index from their history.

    Synchronous despite the 202. The corpus is tens of documents and the
    embedder is local, so this is milliseconds -- an `arq` job would add a queue
    hop and a second failure mode to something that cannot fail slowly. The 202
    is honest about the fact that the answer is not the index itself.
    """
    return ReindexResponse(indexed=await service.reindex(str(child_id)))


@router.post(
    "/children/{child_id}/memory/search",
    response_model=MemorySearchResponse,
)
async def search_memory(
    child_id: UUID,
    body: MemorySearchRequest,
    _access: ChildAccess,
    service: RecommendationServiceDep,
) -> MemorySearchResponse:
    """What retrieval returns for a query. The console's window into the RAG.

    POST rather than GET with a query string: the query is Arabic free text
    about a specific child, and putting it in a URL would write it into every
    access log and every proxy cache along the way.
    """
    documents = await service.search(str(child_id), body.query, k=body.k)
    return MemorySearchResponse(
        query=body.query,
        hits=[MemoryHit(**row) for row in documents_as_rows(documents)],
    )


__all__ = ["router", "set_recommendation_service_factory"]
