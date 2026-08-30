"""SQL for the starting assessment and the learner state it creates.

`SEED_SKILL_STATE` is the important one and it is deliberately narrow. It writes
a row only when there is not one already (`ON CONFLICT DO NOTHING`), so running
the assessment again for a child who has since played does NOT overwrite what
they actually did with what a caregiver remembers. An intake form is the
starting point; once there is real evidence, the real evidence wins.

`p_prior` is set here and nowhere else. The mastery fold reads it and never
writes it, which is what keeps the fold a pure function of the attempts.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

INSERT_ASSESSMENT = text("""
    INSERT INTO starting_assessments (child_id, started_by, form_version)
    VALUES (:child_id, :started_by, :form_version)
    RETURNING id, child_id, status, form_version, answers, area_levels, supports,
              started_at, completed_at
""")

SELECT_OPEN = text("""
    SELECT id FROM starting_assessments
    WHERE child_id = :child_id AND status = 'in_progress'
""")

SELECT_ASSESSMENT = text("""
    SELECT id, child_id, started_by, status, form_version, answers, area_levels,
           supports, started_at, completed_at
    FROM starting_assessments WHERE id = :assessment_id
""")

SELECT_LATEST_FOR_CHILD = text("""
    SELECT id, child_id, status, form_version, answers, area_levels, supports,
           started_at, completed_at
    FROM starting_assessments
    WHERE child_id = :child_id
    ORDER BY started_at DESC
    LIMIT 1
""")

#: One answer, merged into the log. `||` on jsonb is an upsert per key, so
#: answering the same question twice is a CORRECTION rather than a duplicate --
#: the same rule the PGEE assessment uses, for the same reason.
RECORD_ANSWER = text("""
    UPDATE starting_assessments
    SET answers = answers || CAST(:answer AS jsonb), updated_at = now()
    WHERE id = :assessment_id AND status = 'in_progress'
    RETURNING answers
""")

FINALISE = text("""
    UPDATE starting_assessments
    SET status = 'completed',
        area_levels = CAST(:area_levels AS jsonb),
        supports = CAST(:supports AS jsonb),
        completed_at = :now,
        updated_at = now()
    WHERE id = :assessment_id AND status = 'in_progress'
    RETURNING id
""")

#: The first `:limit` skills of a category, in the order a clinician authored.
SELECT_CATEGORY_HEAD = text("""
    SELECT id, code FROM skills
    WHERE is_active AND category = CAST(:category AS skill_category)
    ORDER BY intro_order
    LIMIT :limit
""")

#: DO NOTHING, not DO UPDATE. A child who has already played has a state built
#: from what they did; a form filled in afterwards must not overwrite it.
SEED_SKILL_STATE = text("""
    INSERT INTO skill_states (
        child_id, skill_id, modality, state, p_known, p_prior, p_guess,
        interval_days, ease_factor, due_at, updated_at
    ) VALUES (
        :child_id, :skill_id, CAST(:modality AS modality),
        CAST(:state AS mastery_state), :p_known, :p_prior, 0.5,
        1, 2.30, :due_at, :now
    )
    ON CONFLICT (child_id, skill_id, modality) DO NOTHING
""")


class StartingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def rollback_to_savepoint(self) -> None:
        """Undo the failed INSERT so the session can be used again.

        A failed statement aborts the whole PostgreSQL transaction, and every
        query after it fails with "current transaction is aborted". `rollback()`
        on a session that a test has joined to an outer transaction rolls back
        to the enclosing savepoint rather than discarding the caller's work,
        which is what makes this usable from both the app and the test harness.
        """
        await self._session.rollback()

    async def create(self, *, child_id: UUID, started_by: UUID, form_version: str) -> Any:
        return (
            await self._session.execute(
                INSERT_ASSESSMENT,
                {
                    "child_id": child_id,
                    "started_by": started_by,
                    "form_version": form_version,
                },
            )
        ).one()

    async def open_for_child(self, child_id: UUID) -> UUID | None:
        row = (await self._session.execute(SELECT_OPEN, {"child_id": child_id})).one_or_none()
        return None if row is None else UUID(str(row.id))

    async def get(self, assessment_id: UUID) -> Any | None:
        return (
            await self._session.execute(SELECT_ASSESSMENT, {"assessment_id": assessment_id})
        ).one_or_none()

    async def latest_for_child(self, child_id: UUID) -> Any | None:
        return (
            await self._session.execute(SELECT_LATEST_FOR_CHILD, {"child_id": child_id})
        ).one_or_none()

    async def record_answer(
        self, *, assessment_id: UUID, question_id: str, answer_id: str
    ) -> dict[str, str] | None:
        row = (
            await self._session.execute(
                RECORD_ANSWER,
                {
                    "assessment_id": assessment_id,
                    "answer": json.dumps({question_id: answer_id}),
                },
            )
        ).one_or_none()
        return None if row is None else {str(k): str(v) for k, v in dict(row.answers).items()}

    async def finalise(
        self,
        *,
        assessment_id: UUID,
        area_levels: dict[str, int],
        supports: dict[str, Any],
        now: dt.datetime,
    ) -> bool:
        row = (
            await self._session.execute(
                FINALISE,
                {
                    "assessment_id": assessment_id,
                    "area_levels": json.dumps(area_levels),
                    "supports": json.dumps(supports, ensure_ascii=False),
                    "now": now,
                },
            )
        ).one_or_none()
        return row is not None

    async def category_head(self, *, category: str, limit: int) -> list[Any]:
        return list(
            await self._session.execute(
                SELECT_CATEGORY_HEAD, {"category": category, "limit": limit}
            )
        )

    async def seed_state(self, values: dict[str, Any]) -> None:
        await self._session.execute(SEED_SKILL_STATE, values)


__all__ = ["StartingRepository"]
