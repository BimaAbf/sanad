"""Tutor routes — the runtime loop's HTTP surface.

**Read this before adding a route here.** Only `/children/{child_id}/rewards`
carries a `{child_id}`, so it declares `ChildAccess` and
`tools/guards/route_authorisation.py` checks it. Every other path is keyed by
`{session_id}`, which the guard cannot see — so `TutorService` resolves the
session to its child and calls `assert_child_access` in the first statement of
every method. A route here that reaches the repository directly is an IDOR
against a child's learning record. `tests/unit/test_tutor_routes.py` asserts
the explicit check exists on each one.

The gateway is built once per process by `core/wiring.py` and injected, rather
than constructed per request: it owns a connection pool and the fixture store's
directory handle.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import ServiceUnavailable
from app.modules.identity.deps import ChildAccess, CurrentCaregiver
from app.modules.tutor.schemas import (
    ActivityOut,
    CaregiverReport,
    InspectorOut,
    ResponseIn,
    ResponseOut,
    RewardsOut,
    SessionCreated,
    SessionEnd,
    SessionHistory,
    SessionHistoryItem,
    SessionResult,
    SessionStart,
)
from app.modules.tutor.service import TutorService

router = APIRouter(tags=["tutor"])

TutorServiceFactory = Callable[[AsyncSession], TutorService]

#: Set at wiring time. A module-level hook, exactly as progress and voice do it,
#: so a unit test can drive these routes without a database.
_service_factory: TutorServiceFactory | None = None


def set_tutor_service_factory(factory: TutorServiceFactory | None) -> None:
    global _service_factory
    _service_factory = factory


async def get_tutor_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AsyncIterator[TutorService]:
    if _service_factory is None:
        raise ServiceUnavailable(detail="The tutor is not configured in this deployment.")
    yield _service_factory(session)


TutorServiceDep = Annotated[TutorService, Depends(get_tutor_service)]


@router.post("/tutor/sessions", status_code=status.HTTP_201_CREATED)
async def start_session(
    payload: SessionStart,
    caregiver_id: CurrentCaregiver,
    service: TutorServiceDep,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SessionCreated:
    """Open a session. Returns no activity — the loop asks for that separately.

    Deliberately two calls rather than one. The first activity is a teaching
    decision like every other, and folding it into session creation would make
    the first one special and the retry semantics different.
    """
    row, child = await service.start(child_id=payload.child_id, caregiver_id=caregiver_id)
    await session.commit()
    return SessionCreated(
        session_id=row.id,
        child_id=row.child_id,
        started_at=row.started_at,
        wait_time_ms=int(child.wait_time_ms),
        max_choices=int(child.max_choices),
        audio_rate_pct=int(child.audio_rate_pct),
        calm_mode=bool(child.calm_mode),
    )


@router.post("/tutor/sessions/{session_id}/next")
async def next_activity(
    session_id: UUID,
    caregiver_id: CurrentCaregiver,
    service: TutorServiceDep,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ActivityOut:
    """The AI Brain step: evidence in, one guarded activity out.

    POST rather than GET because it writes — a decision row and an activity row.
    Calling it twice while an activity is unanswered returns that same activity
    rather than deciding again.
    """
    delivered = await service.next_activity(session_id=session_id, caregiver_id=caregiver_id)
    await session.commit()
    if delivered.session_finished:
        return ActivityOut(session_finished=True, wait_time_ms=delivered.wait_time_ms)
    return ActivityOut(
        activity_id=delivered.activity_id,
        ordinal=delivered.ordinal,
        activity_type=delivered.activity_type,
        skill_code=delivered.skill_code,
        difficulty=delivered.difficulty,
        modality=delivered.modality,
        strategy=delivered.strategy,
        support_level=delivered.support_level,
        choice_count=delivered.choice_count,
        presentation=delivered.presentation,
        wait_time_ms=delivered.wait_time_ms,
        decision_source=delivered.model_name,
        reason_codes=list(delivered.reason_codes),
        guardrail_actions=list(delivered.guardrail_actions),
    )


@router.post("/tutor/sessions/{session_id}/respond")
async def respond(
    session_id: UUID,
    payload: ResponseIn,
    caregiver_id: CurrentCaregiver,
    service: TutorServiceDep,
    session: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ResponseOut:
    """The authoritative verdict on one response.

    The header wins over the body when both are present, matching the table in
    docs/05 §1; the body field exists so an offline outbox — which stores a
    body, not headers — drains through the same route.
    """
    key = idempotency_key or payload.idempotency_key
    result = await service.respond(
        session_id=session_id,
        caregiver_id=caregiver_id,
        activity_id=payload.activity_id,
        response=payload.response,
        idempotency_key=key,
        latency_ms=payload.latency_ms,
        reported_prompt_level=payload.prompt_level,
    )
    await session.commit()
    evaluation = result.evaluation
    return ResponseOut(
        activity_id=result.activity_id,
        correct=evaluation.correct,
        outcome=evaluation.outcome.value,
        next_action=evaluation.next_action.value,
        support_action=evaluation.support_action.value,
        reward_delta=result.reward_delta,
        stars_total=result.stars_total,
        achievements_unlocked=list(result.achievements_unlocked),
        duplicate=result.duplicate,
        score=evaluation.score,
        threshold=evaluation.threshold,
        detail=evaluation.detail,
        mastery_before=result.mastery_before,
        mastery_after=result.mastery_after,
        mastery_state=result.mastery_state,
    )


@router.post("/tutor/sessions/{session_id}/end")
async def end_session(
    session_id: UUID,
    payload: SessionEnd,
    caregiver_id: CurrentCaregiver,
    service: TutorServiceDep,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SessionResult:
    """Close the session, compute its facts, persist them, and report.

    Safe to call twice: the completion reward is keyed on the session id, the
    summary upserts, and the `session_end` event is guarded by a NOT EXISTS.
    """
    result = await service.end(
        session_id=session_id,
        caregiver_id=caregiver_id,
        reason=payload.reason,
        minutes=payload.minutes,
    )
    await session.commit()
    facts = result["facts"]
    return SessionResult(
        session_id=result["session_id"],
        ended_at=result["ended_at"],
        activities_completed=facts.activities_completed,
        correct=facts.correct,
        incorrect=facts.incorrect,
        no_response=facts.no_response,
        independent_responses=facts.independent_responses,
        supported_responses=facts.supported_responses,
        skills_practised=list(facts.skills_practised),
        skills_practised_ar=list(facts.skill_labels_ar),
        activity_types=list(facts.activity_types),
        mastery_changes=[
            {
                "skill_code": change.skill_code,
                "skill_label_ar": change.skill_label_ar,
                "from_state": change.from_state,
                "to_state": change.to_state,
            }
            for change in facts.mastery_changes
        ],
        stars_earned=facts.stars_earned,
        stars_total=result["stars_total"],
        achievements_unlocked=list(facts.achievements_unlocked),
        duration_minutes=facts.duration_minutes,
        best_streak=facts.best_streak,
        went_well_ar=list(facts.went_well),
        needs_practice_ar=list(facts.needs_practice),
        narrative_ar=result["narrative_ar"],
        narrative_source=result["narrative_source"],
    )


@router.get("/tutor/sessions/{session_id}/report")
async def session_report(
    session_id: UUID,
    caregiver_id: CurrentCaregiver,
    service: TutorServiceDep,
) -> CaregiverReport:
    """The caregiver's read of a finished session. Facts, then the narrative."""
    report = await service.report(session_id=session_id, caregiver_id=caregiver_id)
    return CaregiverReport(**report)


@router.get("/tutor/sessions/{session_id}/inspector")
async def inspector(
    session_id: UUID,
    caregiver_id: CurrentCaregiver,
    service: TutorServiceDep,
) -> InspectorOut:
    """Why SANAD taught what it taught. Real rows only, never a reconstruction.

    Demo-facing and caregiver-visible; never shown on the child surface. Every
    value is read from `ai_decisions`, `tutor_activities` and `attempts`, and a
    field with no stored value comes back null so the panel can say so.
    """
    data = await service.inspector(session_id=session_id, caregiver_id=caregiver_id)
    return InspectorOut(**data)


@router.get("/children/{child_id}/sessions")
async def child_sessions(
    child_id: UUID,
    _access: ChildAccess,
    caregiver_id: CurrentCaregiver,
    service: TutorServiceDep,
) -> SessionHistory:
    """Every session this child has had, newest first.

    The read that answers "does the history survive a logout": it is a query
    over `play_sessions` and `session_summaries`, so what comes back is what is
    on disk rather than anything a client remembered.
    """
    return SessionHistory(
        child_id=child_id,
        sessions=[
            SessionHistoryItem(**row)
            for row in await service.sessions(child_id=child_id, caregiver_id=caregiver_id)
        ],
    )


@router.get("/children/{child_id}/rewards")
async def child_rewards(
    child_id: UUID,
    _access: ChildAccess,
    caregiver_id: CurrentCaregiver,
    service: TutorServiceDep,
) -> RewardsOut:
    """Stars and achievements, summed from `reward_events`.

    A SUM rather than a stored total, so a reward that was written twice cannot
    be counted twice and a reward that failed to write cannot be shown.
    """
    return RewardsOut(**await service.rewards(child_id=child_id, caregiver_id=caregiver_id))


__all__ = ["router", "set_tutor_service_factory"]
