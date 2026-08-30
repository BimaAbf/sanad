"""All SQL for play sessions and attempts.

`INSERT_ATTEMPT` is the important one. `ON CONFLICT (idempotency_key) DO NOTHING`
is what turns the client's offline outbox from a source of duplicate rows into a
safe replay: the outbox writes an attempt locally with a deterministic key
BEFORE posting, so the same key arrives again after any dropped connection, and
the database — not application logic — is what decides it is the same attempt.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

#: The plan is stored as sent. When a caregiver asks why a session contained
#: what it did, the answer has to be the plan that ran, not a plan regenerated
#: from a curriculum that has since moved on.
INSERT_SESSION = text("""
    INSERT INTO play_sessions (child_id, started_by, plan, plan_source)
    VALUES (:child_id, :started_by, CAST(:plan AS jsonb), :plan_source)
    RETURNING id, child_id, started_at
""")

SELECT_SESSION = text("""
    SELECT id, child_id, started_by, started_at, ended_at,
           activities_done, correct_count
    FROM play_sessions
    WHERE id = :session_id
""")

INSERT_ATTEMPT = text("""
    INSERT INTO attempts (
        session_id, child_id, activity_code, skill_id, modality, result,
        prompt_level, latency_ms, choice_count, selected_skill_id,
        client_ts, idempotency_key
    ) VALUES (
        :session_id, :child_id, :activity_code, :skill_id,
        CAST(:modality AS modality), CAST(:result AS attempt_result),
        CAST(:prompt_level AS prompt_level), :latency_ms, :choice_count,
        :selected_skill_id, :client_ts, :idempotency_key
    )
    ON CONFLICT (idempotency_key) DO NOTHING
    RETURNING id
""")

#: Recomputed from `attempts` rather than incremented per POST. An increment
#: would double-count a replayed batch even though the attempt rows themselves
#: were correctly deduplicated.
END_SESSION = text("""
    UPDATE play_sessions ps
    SET ended_at = :now,
        ended_reason = :reason,
        activities_done = totals.done,
        correct_count = totals.correct
    FROM (
        SELECT count(*) AS done,
               count(*) FILTER (
                   WHERE result IN ('correct', 'accepted_on_effort', 'caregiver_confirmed')
               ) AS correct
        FROM attempts WHERE session_id = :session_id
    ) AS totals
    WHERE ps.id = :session_id
    RETURNING ps.id, ps.activities_done, ps.correct_count
""")

#: The activity plan: what this child has not finished yet, in the curriculum's
#: own order. `intro_order` is the sequencing a clinician authored, so following
#: it is following the curriculum rather than second-guessing it.
SELECT_PLAN_SKILLS = text("""
    SELECT s.id, s.code, s.label_ar, s.label_egy, s.alt_text_ar, s.category::text AS category,
           COALESCE(st.state::text, 'not_started') AS state
    FROM skills s
    LEFT JOIN skill_states st ON st.skill_id = s.id AND st.child_id = :child_id
    WHERE s.is_active
      AND COALESCE(st.state::text, 'not_started') NOT IN ('mastered', 'retained')
    ORDER BY s.intro_order
    LIMIT :limit
""")

#: Distractors. Same category as the target, so the choice is a real
#: discrimination ("show me the red one" against another colour) rather than a
#: giveaway between a colour and a chair.
SELECT_DISTRACTORS = text("""
    SELECT s.id, s.code, s.label_ar, s.label_egy, s.alt_text_ar
    FROM skills s
    WHERE s.is_active AND s.category = CAST(:category AS skill_category)
      AND s.code <> :code
    ORDER BY s.intro_order
    LIMIT :limit
""")

#: `expanding=True` renders the list as an IN-list of individual binds.
#: A bare list bound to `= ANY(:codes)` is driver-dependent; this is not.
SELECT_SKILL_IDS = text("""
    SELECT code, id FROM skills WHERE code IN :codes
""").bindparams(bindparam("codes", expanding=True))

#: One `session_end` event, which is what `progress/history.py` reads to build
#: every rollup. Without this row a completed session leaves no trace on the
#: caregiver dashboard, which is the state the product was in.
#: The NOT EXISTS guard, not ON CONFLICT, for the reason spelled out at
#: `progress/repository.py::INSERT_EVENT`: `events` has no unique constraint an
#: ON CONFLICT clause can name that also deduplicates.
INSERT_SESSION_END_EVENT = text("""
    INSERT INTO events (child_id, caregiver_id, name, props, client_ts, idempotency_key)
    SELECT :child_id, :caregiver_id, 'session_end', CAST(:props AS jsonb),
           :client_ts, :idempotency_key
    WHERE NOT EXISTS (
        SELECT 1 FROM events WHERE idempotency_key = :idempotency_key
    )
""")


class PlayRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_session(
        self, *, child_id: UUID, started_by: UUID, plan: list[dict[str, Any]], plan_source: str
    ) -> Any:
        return (
            await self._session.execute(
                INSERT_SESSION,
                {
                    "child_id": child_id,
                    "started_by": started_by,
                    "plan": json.dumps(plan, ensure_ascii=False),
                    "plan_source": plan_source,
                },
            )
        ).one()

    async def get_session(self, session_id: UUID) -> Any | None:
        return (await self._session.execute(SELECT_SESSION, {"session_id": session_id})).first()

    async def plan_skills(self, *, child_id: UUID, limit: int) -> list[Any]:
        return list(
            await self._session.execute(SELECT_PLAN_SKILLS, {"child_id": child_id, "limit": limit})
        )

    async def distractors(self, *, category: str, code: str, limit: int) -> list[Any]:
        return list(
            await self._session.execute(
                SELECT_DISTRACTORS, {"category": category, "code": code, "limit": limit}
            )
        )

    async def skill_ids(self, codes: list[str]) -> dict[str, UUID]:
        if not codes:
            return {}
        rows = await self._session.execute(SELECT_SKILL_IDS, {"codes": codes})
        return {str(row.code): row.id for row in rows}

    async def record_attempt(self, values: dict[str, Any]) -> bool:
        """True when the row was written, False when the key was already used."""
        result = await self._session.execute(INSERT_ATTEMPT, values)
        return result.first() is not None

    async def end_session(self, *, session_id: UUID, reason: str, now: dt.datetime) -> Any | None:
        return (
            await self._session.execute(
                END_SESSION, {"session_id": session_id, "reason": reason, "now": now}
            )
        ).first()

    async def activity_attempt(self, *, session_id: UUID, idempotency_key: str) -> Any | None:
        result = await self._session.execute(
            text("""
                SELECT a.id, a.child_id, a.session_id, a.activity_code, a.skill_id,
                       a.modality::text AS modality, a.result::text AS result,
                       a.prompt_level::text AS prompt_level, a.latency_ms,
                       a.choice_count, a.client_ts
                FROM attempts a
                WHERE a.session_id = :session_id AND a.idempotency_key = :idempotency_key
            """),
            {"session_id": session_id, "idempotency_key": idempotency_key},
        )
        return result.first()

    async def record_session_end_event(
        self,
        *,
        child_id: UUID,
        caregiver_id: UUID,
        props: dict[str, Any],
        client_ts: dt.datetime,
        idempotency_key: str,
    ) -> None:
        await self._session.execute(
            INSERT_SESSION_END_EVENT,
            {
                "child_id": child_id,
                "caregiver_id": caregiver_id,
                "props": json.dumps(props, ensure_ascii=False),
                "client_ts": client_ts,
                "idempotency_key": idempotency_key,
            },
        )


__all__ = ["PlayRepository"]
