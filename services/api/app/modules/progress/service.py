"""Progress business rules.

The service is thin on purpose: everything that decides what a caregiver sees
lives in `domain/views.py`, and everything that decides a number lives in
`domain/rollup.py`. What is left here is fetching, and the two rollup paths.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import structlog

from app.modules.progress.domain.periods import ALL_TIME, day_key, local_date
from app.modules.progress.domain.rollup import (
    Rollup,
    SessionFact,
    SkillStateFact,
    rebuild_all,
    rebuild_for_session,
)
from app.modules.progress.domain.views import (
    Activity,
    AssessmentPoint,
    SkillCard,
    build_journey,
    build_skills,
    build_today,
)
from app.modules.progress.schemas import (
    ActivitySuggestion,
    AssessmentSummary,
    EventBatch,
    JourneyPoint,
    JourneyResponse,
    SkillCardOut,
    SkillsResponse,
    TodayResponse,
)

logger = structlog.get_logger(__name__)


#: A database row, as SQLAlchemy hands it back: keys are known, value types are
#: not. Coerced at the boundary by `_int` / `_optional_float` rather than
#: sprinkled with casts, so there is one place where a schema change bites.
Row = dict[str, Any]


class ProgressStore(Protocol):
    """What the service needs from persistence. Implemented by the repository
    against Postgres, and by a fake in the tests."""

    async def record_events(self, rows: Sequence[Row]) -> int: ...

    async def upsert_rollups(self, rollups: Sequence[Rollup]) -> None: ...

    async def rollups(self, child_id: str, *, pattern: str = "%") -> list[Row]: ...

    async def skill_cards(self, child_id: str) -> list[Row]: ...


class HistorySource(Protocol):
    async def sessions(self, child_id: str) -> list[SessionFact]: ...

    async def skill_states(self, child_id: str) -> list[SkillStateFact]: ...

    async def assessment_points(self, child_id: str) -> list[AssessmentPoint]: ...

    async def assessment_summaries(self, child_id: str) -> list[AssessmentSummary]: ...

    async def revisit_candidates(self, child_id: str) -> list[Activity]: ...

    async def suggestion(self, child_id: str) -> Activity | None: ...


@dataclass(frozen=True, slots=True)
class ProgressService:
    store: ProgressStore
    history: HistorySource

    # --- ingestion ---------------------------------------------------------

    async def ingest(self, *, caregiver_id: UUID, batch: EventBatch) -> int:
        rows: list[Row] = [
            {
                "child_id": str(event.child_id) if event.child_id else None,
                "caregiver_id": str(caregiver_id),
                "name": event.name,
                "props": json.dumps(event.props, ensure_ascii=False),
                "client_ts": event.client_ts,
                "idempotency_key": event.idempotency_key,
            }
            for event in batch.events
        ]
        accepted = await self.store.record_events(rows)
        logger.info("events_ingested", accepted=accepted, submitted=len(rows))
        return accepted

    # --- rollups -----------------------------------------------------------

    async def rollup_on_session_end(self, *, child_id: str, session: SessionFact) -> list[Rollup]:
        """The incremental path. Recomputes the affected periods in full."""
        rollups = rebuild_for_session(
            child_id=child_id,
            session=session,
            all_sessions=await self.history.sessions(child_id),
            states=await self.history.skill_states(child_id),
        )
        await self.store.upsert_rollups(rollups)
        return rollups

    async def rebuild_nightly(self, *, child_id: str) -> list[Rollup]:
        """The correctness backstop. Every period, from scratch."""
        rollups = rebuild_all(
            child_id=child_id,
            sessions=await self.history.sessions(child_id),
            states=await self.history.skill_states(child_id),
        )
        await self.store.upsert_rollups(rollups)
        return rollups

    # --- views -------------------------------------------------------------

    async def _rollup_index(self, child_id: str) -> dict[str, Rollup]:
        rows = await self.store.rollups(child_id)
        return {
            str(row["period"]): Rollup(
                child_id=child_id,
                period=str(row["period"]),
                sessions=_int(row.get("sessions")),
                minutes=_int(row.get("minutes")),
                attempts=_int(row.get("attempts")),
                accuracy=_optional_float(row.get("accuracy")),
                skills_mastered=_int(row.get("skills_mastered")),
                skills_practising=_int(row.get("skills_practising")),
                by_category=dict(row.get("by_category") or {}),
            )
            for row in rows
        }

    async def today(self, child_id: str, *, today: dt.datetime) -> TodayResponse:
        index = await self._rollup_index(child_id)
        date = local_date(today)
        view = build_today(
            today=date,
            day_rollup=index.get(day_key(date)),
            previous_day_rollup=index.get(day_key(date - dt.timedelta(days=1))),
            history=[rollup for rollup in index.values() if rollup.period.startswith("day:")],
            suggestion=await self.history.suggestion(child_id),
            revisit_candidates=await self.history.revisit_candidates(child_id),
            assessment_points=await self.history.assessment_points(child_id),
        )
        return TodayResponse(
            date=view.date,
            sessions=view.sessions,
            minutes=view.minutes,
            attempts=view.attempts,
            streak_days=view.streak_days,
            suggestion=_activity_out(view.suggestion),
            revisit_plan=[a for a in map(_activity_out, view.revisit_plan) if a is not None],
            regression_detected=view.regression_detected,
        )

    async def skills(self, child_id: str) -> SkillsResponse:
        rows = await self.store.skill_cards(child_id)
        cards = [
            SkillCard(
                skill_id=str(row["skill_id"]),
                code=str(row["code"]),
                label_ar=str(row["label_ar"]),
                category=str(row["category"]),
                # A skill the child has never seen has no state row at all.
                state=str(row.get("state") or "not_started"),
                p_known=_optional_float(row.get("p_known")) or 0.0,
                due_at=row.get("due_at"),
                last_seen_at=row.get("last_seen_at"),
            )
            for row in rows
        ]
        view = build_skills(cards)
        return SkillsResponse(
            total=view.total,
            mastered=view.mastered,
            practising=view.practising,
            not_started=view.not_started,
            by_category={
                category: [
                    SkillCardOut(
                        skill_id=card.skill_id,
                        code=card.code,
                        label_ar=card.label_ar,
                        category=card.category,
                        state=card.state,
                        p_known=card.p_known,
                        due_at=card.due_at,
                        last_seen_at=card.last_seen_at,
                    )
                    for card in cards_in
                ]
                for category, cards_in in view.by_category.items()
            },
        )

    async def journey(self, child_id: str) -> JourneyResponse:
        view = build_journey(
            await self.history.assessment_points(child_id),
            revisit_candidates=await self.history.revisit_candidates(child_id),
        )
        return JourneyResponse(
            status="ok" if view.status == "ok" else "insufficient_data",
            points=[
                JourneyPoint(
                    assessment_id=point.assessment_id,
                    completed_at=point.completed_at,
                    domain_da=point.domain_da,
                    skills_mastered=point.skills_mastered,
                )
                for point in view.points
            ],
            copy_key=view.copy_key,
            revisit_plan=[a for a in map(_activity_out, view.revisit_plan) if a is not None],
        )

    async def assessments(self, child_id: str) -> list[AssessmentSummary]:
        return await self.history.assessment_summaries(child_id)


def _int(value: Any) -> int:
    return int(value) if value is not None else 0


def _optional_float(value: Any) -> float | None:
    return float(value) if value is not None else None


def _activity_out(activity: Activity | None) -> ActivitySuggestion | None:
    if activity is None:
        return None
    return ActivitySuggestion(
        activity_code=activity.activity_code,
        skill_id=activity.skill_id,
        label_ar=activity.label_ar,
    )


__all__ = ["ALL_TIME", "HistorySource", "ProgressService", "ProgressStore"]
