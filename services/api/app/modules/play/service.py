"""Play session business rules.

Three things happen here and they are the three that were missing:

1. **A session gets a plan.** The child app shipped with a hardcoded
   `PLACEHOLDER_ACTIVITIES` array of one activity. The plan is built from the
   `skills` catalogue in `intro_order`, skipping what this child has already
   mastered, with distractors drawn from the same category so the choice is a
   real discrimination.
2. **An attempt gets stored.** The outbox posted into a sender that returned
   `{ok: true}` and dropped the payload on the floor. `attempts` is what makes a
   confusion pattern, a mastery window or a BKT update computable at all.
3. **Ending a session writes a `session_end` event.** That is the single row
   `progress/history.py` reads to build every rollup, so without it a completed
   session left no trace on the caregiver dashboard.

Authorisation, as in `assessment/service.py`: `{session_id}` is not
`{child_id}`, so GUARD 1 cannot see these routes. Every method resolves the
session to its child and calls `assert_child_access` explicitly.

`plan_source` is `deterministic_fallback` and says so. The AI planner is the
tutor orchestrator's job; labelling this plan `ai` because a plan came back
would make the console unable to tell one from the other.
"""

from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID

import structlog

from app.core.errors import Conflict, NotFound
from app.modules.children.repository import ChildrenRepository
from app.modules.identity.domain import Role
from app.modules.identity.service import IdentityService
from app.modules.learning.service import MasteryService
from app.modules.play.repository import PlayRepository
from app.modules.play.schemas import (
    ActivityOut,
    AttemptAccepted,
    AttemptBatch,
    AttemptIn,
    ChoiceOut,
    SessionCreated,
    SessionSummary,
)
from app.modules.progress.domain.rollup import SessionFact
from app.modules.progress.service import ProgressService

logger = structlog.get_logger(__name__)

#: Activities per minute of session. One is not a throughput estimate — it is
#: the pace docs/04e describes, where an 8-second wait and an 800ms pause between
#: activities are the point rather than overhead.
ACTIVITIES_PER_MINUTE = 1

#: Floor and ceiling on the plan length regardless of the minutes asked for.
MIN_ACTIVITIES = 3
MAX_ACTIVITIES = 12

PLAN_SOURCE = "deterministic_fallback"

#: docs/04e: the instruction is Egyptian Arabic, spoken. `label_egy` is the
#: colloquial label; `label_ar` is the MSA one and is not what Nour says.
INSTRUCTION_TEMPLATE = "وريني {label}"


class PlayService:
    def __init__(
        self,
        *,
        repo: PlayRepository,
        children: ChildrenRepository,
        identity: IdentityService,
        progress: ProgressService,
        mastery: MasteryService,
    ) -> None:
        self._repo = repo
        self._children = children
        self._identity = identity
        self._progress = progress
        self._mastery = mastery

    # --- sessions ----------------------------------------------------------

    async def start(
        self, *, child_id: UUID, caregiver_id: UUID, minutes: int | None
    ) -> SessionCreated:
        await self._identity.assert_child_access(
            caregiver_id=caregiver_id, child_id=child_id, min_role=Role.CO_CAREGIVER
        )
        child = await self._child_or_404(child_id)

        wanted = minutes if minutes is not None else int(child.session_minutes)
        count = max(MIN_ACTIVITIES, min(MAX_ACTIVITIES, wanted * ACTIVITIES_PER_MINUTE))
        activities = await self._build_plan(
            child_id=child_id, count=count, max_choices=int(child.max_choices)
        )
        if not activities:
            # An empty catalogue is a deployment that never ran `sanad seed`.
            # Saying so beats returning a session with nothing in it, which the
            # child app would render as an immediate closing scene.
            raise Conflict(detail="No activities are available for this child yet.")

        row = await self._repo.create_session(
            child_id=child_id,
            started_by=caregiver_id,
            plan=[activity.model_dump(mode="json") for activity in activities],
            plan_source=PLAN_SOURCE,
        )
        logger.info(
            "play_session_started",
            session_id=str(row.id),
            child_id=str(child_id),
            activities=len(activities),
        )
        return SessionCreated(
            session_id=row.id,
            child_id=child_id,
            started_at=row.started_at,
            plan_source=PLAN_SOURCE,
            wait_time_ms=int(child.wait_time_ms),
            max_choices=int(child.max_choices),
            calm_mode=bool(child.calm_mode),
            activities=activities,
        )

    async def _build_plan(
        self, *, child_id: UUID, count: int, max_choices: int
    ) -> list[ActivityOut]:
        targets = await self._repo.plan_skills(child_id=child_id, limit=count)
        activities: list[ActivityOut] = []
        for target in targets:
            # One fewer distractor than the child's configured choice count, and
            # never more than the category can supply. A choice count the child
            # cannot handle is the single most common cause of a session that
            # feels like a test.
            pool = await self._repo.distractors(
                category=str(target.category), code=str(target.code), limit=max(max_choices - 1, 1)
            )
            choices = [
                ChoiceOut(
                    skill_id=target.id,
                    code=str(target.code),
                    label_ar=str(target.label_ar),
                    alt_ar=str(target.alt_text_ar),
                    correct=True,
                )
            ]
            choices.extend(
                ChoiceOut(
                    skill_id=row.id,
                    code=str(row.code),
                    label_ar=str(row.label_ar),
                    alt_ar=str(row.alt_text_ar),
                    correct=False,
                )
                for row in pool
            )
            if len(choices) < 2:
                # A one-choice activity is not a discrimination. Skip rather
                # than present something that teaches nothing.
                continue
            activities.append(
                ActivityOut(
                    activity_code=f"listen_point:{target.code}",
                    skill_id=target.id,
                    skill_code=str(target.code),
                    instruction_ar=INSTRUCTION_TEMPLATE.format(
                        label=str(target.label_egy or target.label_ar)
                    ),
                    choices=choices,
                )
            )
        return activities

    # --- attempts ----------------------------------------------------------

    async def record_attempts(
        self, *, session_id: UUID, caregiver_id: UUID, batch: AttemptBatch
    ) -> AttemptAccepted:
        session = await self._require(session_id, caregiver_id)

        codes = {a.skill_code for a in batch.attempts}
        codes.update(a.selected_skill_code for a in batch.attempts if a.selected_skill_code)
        ids = await self._repo.skill_ids(sorted(codes))

        accepted = 0
        for attempt in batch.attempts:
            skill_id = ids.get(attempt.skill_code)
            if skill_id is None:
                # A code this deployment's catalogue does not have. Dropping it
                # loses one attempt; failing the batch would make the client
                # retry forever and stall every attempt behind it.
                logger.warning("attempt_unknown_skill", skill_code=attempt.skill_code)
                continue
            if await self._repo.record_attempt(_attempt_values(attempt, session, skill_id, ids)):
                accepted += 1
        return AttemptAccepted(accepted=accepted, duplicates=len(batch.attempts) - accepted)

    # --- ending ------------------------------------------------------------

    async def end(
        self, *, session_id: UUID, caregiver_id: UUID, reason: str, minutes: int
    ) -> SessionSummary:
        session = await self._require(session_id, caregiver_id)
        now = _now()
        row = await self._repo.end_session(session_id=session_id, reason=reason, now=now)
        if row is None:
            raise NotFound(detail="Session not found.")

        child_id = str(session.child_id)
        fact = SessionFact(
            session_id=str(session_id),
            child_id=child_id,
            started_at=session.started_at,
            minutes=minutes,
            attempts=int(row.activities_done),
            correct=int(row.correct_count),
            by_category={},
        )
        # The event first, then the rollup. The rollup reads `events` back, so
        # the ordering is what makes today's numbers include this session rather
        # than every session but this one.
        await self._repo.record_session_end_event(
            child_id=session.child_id,
            caregiver_id=caregiver_id,
            props={
                "session_id": str(session_id),
                "minutes": minutes,
                "attempts": fact.attempts,
                "correct": fact.correct,
                "by_category": {},
            },
            client_ts=now,
            idempotency_key=f"session_end:{session_id}",
        )
        await self._progress.rollup_on_session_end(child_id=child_id, session=fact)

        # The mastery loop, last: it reads `attempts`, which every earlier step
        # has already finished writing. Before this call a child could play
        # forever without a single skill leaving `not_started` -- the attempts
        # were stored and nothing ever folded them into a state.
        child = await self._child_or_404(session.child_id)
        transitions = await self._mastery.apply_session(
            child_id=session.child_id,
            session_id=session_id,
            wait_time_ms=int(child.wait_time_ms),
            now=now,
        )

        logger.info(
            "play_session_ended",
            session_id=str(session_id),
            reason=reason,
            transitions=len(transitions),
        )
        return SessionSummary(
            session_id=session_id,
            ended_at=now,
            activities_done=fact.attempts,
            correct_count=fact.correct,
        )

    # --- internals ---------------------------------------------------------

    async def _require(self, session_id: UUID, caregiver_id: UUID) -> Any:
        session = await self._repo.get_session(session_id)
        if session is None:
            raise NotFound(detail="Session not found.")
        await self._identity.assert_child_access(
            caregiver_id=caregiver_id, child_id=session.child_id, min_role=Role.CO_CAREGIVER
        )
        return session

    async def _child_or_404(self, child_id: UUID) -> Any:
        child = await self._children.get_child(child_id)
        if child is None:
            raise NotFound(detail="Child not found.")
        return child


def _attempt_values(
    attempt: AttemptIn, session: Any, skill_id: UUID, ids: dict[str, UUID]
) -> dict[str, Any]:
    return {
        "session_id": session.id,
        "child_id": session.child_id,
        "activity_code": attempt.activity_code,
        "skill_id": skill_id,
        "modality": attempt.modality,
        "result": attempt.result,
        "prompt_level": attempt.prompt_level,
        "latency_ms": attempt.latency_ms,
        "choice_count": attempt.choice_count,
        "selected_skill_id": (
            ids.get(attempt.selected_skill_code) if attempt.selected_skill_code else None
        ),
        "client_ts": attempt.client_ts or _now(),
        "idempotency_key": attempt.idempotency_key,
    }


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


__all__ = ["PlayService"]
