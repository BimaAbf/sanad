"""The `HistorySource` the progress service has always required.

`ProgressService` takes a `store` and a `history`. The store had a real
implementation (`ProgressRepository`); the history had none anywhere in `app/`
-- only test fakes -- which is half of why `set_progress_service_factory` was
never called and all four `/progress/*` routes answered 503 in every running
instance.

`assessment_points` and `assessment_summaries` used to return `[]`
unconditionally, because there was no `assessments` table -- the engine (P04)
was domain logic with nowhere to persist. That is fixed: migration
`0010_assessments` created the two tables and `assessment/` now writes to them,
so both methods read real rows and the journey stops answering
`insufficient_data` once a child has three completed assessments.

`domain_da` is read straight off the assessment row rather than replayed and
rescored here. It is written once, at finalisation, and cannot change
afterwards; replaying six assessments of several hundred items each on a
dashboard GET would be the slowest thing in the product for a constant.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.progress.domain.rollup import SessionFact, SkillStateFact
from app.modules.progress.domain.views import Activity, AssessmentPoint
from app.modules.progress.schemas import AssessmentSummary

logger = structlog.get_logger(__name__)

#: The one event name this module reads. The client's outbox drains into
#: POST /events; a session that ended emits exactly one of these, carrying the
#: totals the rollup needs. Naming it here, in the only place that consumes it,
#: keeps the contract in one file instead of implied across two codebases.
SESSION_END_EVENT = "session_end"

SELECT_SESSIONS = text("""
    SELECT props ->> 'session_id'                       AS session_id,
           child_id::text                               AS child_id,
           COALESCE(client_ts, server_ts)               AS started_at,
           COALESCE((props ->> 'minutes')::int, 0)      AS minutes,
           COALESCE((props ->> 'attempts')::int, 0)     AS attempts,
           COALESCE((props ->> 'correct')::int, 0)      AS correct,
           COALESCE(props -> 'by_category', '{}'::jsonb) AS by_category
    FROM events
    WHERE child_id = CAST(:child_id AS uuid)
      AND name = :event_name
      AND props ? 'session_id'
    ORDER BY COALESCE(client_ts, server_ts)
""")

SELECT_SKILL_STATES = text("""
    SELECT s.code AS skill_id, s.category::text AS category,
           COALESCE(st.state::text, 'not_started') AS state
    FROM skills s
    LEFT JOIN skill_states st
           ON st.skill_id = s.id AND st.child_id = CAST(:child_id AS uuid)
    WHERE s.is_active
    ORDER BY s.category, s.intro_order
""")

#: The next thing to do: the earliest-introduced active skill this child has not
#: finished. `intro_order` is the curriculum's own sequencing, so this follows
#: the curriculum rather than second-guessing it.
SELECT_SUGGESTION = text("""
    SELECT s.id::text AS skill_id, s.code, s.label_ar
    FROM skills s
    LEFT JOIN skill_states st
           ON st.skill_id = s.id AND st.child_id = CAST(:child_id AS uuid)
    WHERE s.is_active
      AND COALESCE(st.state::text, 'not_started') NOT IN ('mastered', 'retained')
    ORDER BY s.intro_order
    LIMIT 1
""")

#: Candidates for a revisit: what has lapsed, and what is due for review.
#: `build_revisit_plan` decides how many of these become a plan -- three, or
#: none. This returns candidates, never a plan.
SELECT_REVISIT = text("""
    SELECT s.id::text AS skill_id, s.code, s.label_ar
    FROM skill_states st
    JOIN skills s ON s.id = st.skill_id
    WHERE st.child_id = CAST(:child_id AS uuid)
      AND s.is_active
      AND (st.state = 'lapsed' OR (st.due_at IS NOT NULL AND st.due_at <= now()))
    ORDER BY st.due_at NULLS LAST
    LIMIT 12
""")


#: The journey series. Completed assessments only, oldest first: the chart is a
#: time series and `build_journey` applies the three-point rule to it.
SELECT_ASSESSMENT_POINTS = text("""
    SELECT id::text AS assessment_id, completed_at, domain_da, skills_mastered
    FROM assessments
    WHERE child_id = CAST(:child_id AS uuid)
      AND status = 'completed' AND completed_at IS NOT NULL
    ORDER BY completed_at
""")

SELECT_ASSESSMENT_SUMMARIES = text("""
    SELECT id::text AS assessment_id, status::text AS status, started_at, completed_at
    FROM assessments
    WHERE child_id = CAST(:child_id AS uuid)
    ORDER BY started_at DESC
""")


def _activity(row: Any) -> Activity:
    """A skill rendered as something to do.

    `activity_code` is `<kind>:<skill code>`. The kind is fixed at
    `listen_point` because that is the only activity kind the child app can
    currently render; when `content/` grows a real activity table this becomes a
    lookup, and the shape of the code does not have to change.
    """
    return Activity(
        activity_code=f"listen_point:{row.code}",
        skill_id=row.skill_id,
        label_ar=row.label_ar,
    )


class ProgressHistory:
    """`HistorySource` over Postgres."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def sessions(self, child_id: str) -> list[SessionFact]:
        rows = await self._session.execute(
            SELECT_SESSIONS, {"child_id": child_id, "event_name": SESSION_END_EVENT}
        )
        facts: list[SessionFact] = []
        for row in rows:
            by_category = row.by_category if isinstance(row.by_category, dict) else {}
            facts.append(
                SessionFact(
                    session_id=str(row.session_id),
                    child_id=str(row.child_id),
                    started_at=row.started_at,
                    minutes=int(row.minutes),
                    attempts=int(row.attempts),
                    correct=int(row.correct),
                    by_category={str(k): int(v) for k, v in by_category.items()},
                )
            )
        return facts

    async def skill_states(self, child_id: str) -> list[SkillStateFact]:
        rows = await self._session.execute(SELECT_SKILL_STATES, {"child_id": child_id})
        return [
            SkillStateFact(skill_id=row.skill_id, category=row.category, state=row.state)
            for row in rows
        ]

    async def assessment_points(self, child_id: str) -> list[AssessmentPoint]:
        """The journey series: one point per COMPLETED assessment, oldest first.

        In-progress assessments are excluded by the query, not filtered here. A
        half-administered assessment has a developmental age computed from a
        partial answer log; putting that on a trend line next to two finished
        ones would show a family a dip that is an artefact of when they stopped.
        """
        rows = await self._session.execute(SELECT_ASSESSMENT_POINTS, {"child_id": child_id})
        points: list[AssessmentPoint] = []
        for row in rows:
            domain_da = row.domain_da if isinstance(row.domain_da, dict) else {}
            points.append(
                AssessmentPoint(
                    assessment_id=str(row.assessment_id),
                    completed_at=row.completed_at.date(),
                    domain_da={str(k): float(v) for k, v in domain_da.items()},
                    skills_mastered=int(row.skills_mastered),
                )
            )
        return points

    async def assessment_summaries(self, child_id: str) -> list[AssessmentSummary]:
        """Every assessment, finished or not, newest first — this is the list a
        caregiver resumes from, so an unfinished one has to appear."""
        rows = await self._session.execute(SELECT_ASSESSMENT_SUMMARIES, {"child_id": child_id})
        return [
            AssessmentSummary(
                assessment_id=str(row.assessment_id),
                status=str(row.status),
                started_at=row.started_at,
                completed_at=row.completed_at,
                # The report renderer is docs/05 §4.3 and is not built. Saying
                # `true` here would put a link in the UI that 404s.
                report_available=False,
            )
            for row in rows
        ]

    async def revisit_candidates(self, child_id: str) -> list[Activity]:
        rows = await self._session.execute(SELECT_REVISIT, {"child_id": child_id})
        return [_activity(row) for row in rows]

    async def suggestion(self, child_id: str) -> Activity | None:
        row = (await self._session.execute(SELECT_SUGGESTION, {"child_id": child_id})).first()
        return _activity(row) if row is not None else None


__all__ = ["SESSION_END_EVENT", "ProgressHistory"]
