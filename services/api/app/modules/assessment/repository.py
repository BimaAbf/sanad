"""All SQL for assessments. Raw text(), the same style as progress/history.py.

Two invariants live in this file rather than in the service:

* the answer log is append-only -- `supersede` stamps a row, it never deletes
  one, and `record_answer` always appends at the next sequence;
* `next_sequence` is computed inside the INSERT rather than read-then-written,
  so two concurrent answers cannot land on the same ordinal.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

INSERT_ASSESSMENT = text("""
    INSERT INTO assessments (child_id, started_by, bank_version, child_months, status)
    VALUES (:child_id, :started_by, :bank_version, :child_months, 'in_progress')
    RETURNING id, child_id, bank_version, child_months, status, started_at
""")

SELECT_ASSESSMENT = text("""
    SELECT id, child_id, started_by, bank_version, child_months, status::text AS status,
           domain_da, skills_mastered, started_at, completed_at
    FROM assessments
    WHERE id = :assessment_id
""")

#: Superseded rows are excluded here, not filtered by the caller: a corrected
#: answer must never reach `engine.replay`, and the one query that feeds replay
#: is the right place to guarantee it.
SELECT_ANSWERS = text("""
    SELECT id, item_id, verdict::text AS verdict, propagated, sequence
    FROM assessment_answers
    WHERE assessment_id = :assessment_id AND superseded_at IS NULL
    ORDER BY sequence
""")

#: `sequence` comes from the table itself inside the same statement. Reading a
#: MAX into Python and writing it back would let two concurrent answers collide.
INSERT_ANSWER = text("""
    INSERT INTO assessment_answers
        (assessment_id, item_id, verdict, source, propagated, sequence, idempotency_key)
    SELECT :assessment_id, :item_id, CAST(:verdict AS response_verdict),
           CAST(:source AS response_source), :propagated,
           COALESCE((SELECT MAX(sequence) FROM assessment_answers
                     WHERE assessment_id = :assessment_id), -1) + 1,
           :idempotency_key
    ON CONFLICT (assessment_id, idempotency_key)
        WHERE idempotency_key IS NOT NULL DO NOTHING
    RETURNING id
""")

#: Has this exact client key already been recorded? Checked BEFORE anything is
#: superseded -- see `service.answer`.
SELECT_BY_KEY = text("""
    SELECT 1 FROM assessment_answers
    WHERE assessment_id = :assessment_id AND idempotency_key = :idempotency_key
    LIMIT 1
""")

SUPERSEDE_ANSWERS = text("""
    UPDATE assessment_answers
    SET superseded_at = :now
    WHERE assessment_id = :assessment_id AND item_id = :item_id AND superseded_at IS NULL
""")

FINALISE = text("""
    UPDATE assessments
    SET status = 'completed', completed_at = :now, updated_at = :now,
        domain_da = CAST(:domain_da AS jsonb), skills_mastered = :skills_mastered
    WHERE id = :assessment_id AND status <> 'completed'
    RETURNING id
""")

# The two child-scoped read queries -- the journey series and the resume list --
# deliberately do NOT live here. `progress/history.py` owns every read the
# caregiver dashboard makes, because `ProgressService` is built from one
# `HistorySource` and splitting its queries across two repositories is how a
# dashboard ends up with two different definitions of "completed".

#: How many skills this child has actually mastered, snapshotted onto the
#: assessment so the journey point is a fixed historical fact rather than a
#: number that silently rewrites itself every time the child plays.
COUNT_MASTERED = text("""
    SELECT count(*) AS n FROM skill_states
    WHERE child_id = :child_id AND state IN ('mastered', 'retained')
""")

#: In-progress assessments for one child. Starting a second one while the first
#: is open is almost always a caregiver who closed the tab, not a real second
#: administration.
SELECT_OPEN = text("""
    SELECT id FROM assessments
    WHERE child_id = :child_id AND status IN ('draft', 'in_progress', 'paused')
    ORDER BY started_at DESC LIMIT 1
""")


class AssessmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, *, child_id: UUID, started_by: UUID, bank_version: str, child_months: float
    ) -> Any:
        row = (
            await self._session.execute(
                INSERT_ASSESSMENT,
                {
                    "child_id": child_id,
                    "started_by": started_by,
                    "bank_version": bank_version,
                    "child_months": child_months,
                },
            )
        ).one()
        return row

    async def get(self, assessment_id: UUID) -> Any | None:
        return (
            await self._session.execute(SELECT_ASSESSMENT, {"assessment_id": assessment_id})
        ).first()

    async def open_for_child(self, child_id: UUID) -> UUID | None:
        row = (await self._session.execute(SELECT_OPEN, {"child_id": child_id})).first()
        return row.id if row is not None else None

    async def answers(self, assessment_id: UUID) -> list[Any]:
        return list(await self._session.execute(SELECT_ANSWERS, {"assessment_id": assessment_id}))

    async def record_answer(
        self,
        *,
        assessment_id: UUID,
        item_id: str,
        verdict: str,
        source: str,
        propagated: bool,
        idempotency_key: str | None,
    ) -> bool:
        """Append one answer. False means the idempotency key was already used."""
        result = await self._session.execute(
            INSERT_ANSWER,
            {
                "assessment_id": assessment_id,
                "item_id": item_id,
                "verdict": verdict,
                "source": source,
                "propagated": propagated,
                "idempotency_key": idempotency_key,
            },
        )
        return result.first() is not None

    async def has_key(self, *, assessment_id: UUID, idempotency_key: str) -> bool:
        row = (
            await self._session.execute(
                SELECT_BY_KEY,
                {"assessment_id": assessment_id, "idempotency_key": idempotency_key},
            )
        ).first()
        return row is not None

    async def supersede(self, *, assessment_id: UUID, item_id: str, now: dt.datetime) -> None:
        await self._session.execute(
            SUPERSEDE_ANSWERS,
            {"assessment_id": assessment_id, "item_id": item_id, "now": now},
        )

    async def finalise(
        self,
        *,
        assessment_id: UUID,
        domain_da: dict[str, float],
        skills_mastered: int,
        now: dt.datetime,
    ) -> bool:
        result = await self._session.execute(
            FINALISE,
            {
                "assessment_id": assessment_id,
                "domain_da": json.dumps(domain_da),
                "skills_mastered": skills_mastered,
                "now": now,
            },
        )
        return result.first() is not None

    async def count_mastered(self, child_id: UUID) -> int:
        row = (await self._session.execute(COUNT_MASTERED, {"child_id": child_id})).one()
        return int(row.n)


__all__ = ["AssessmentRepository"]
