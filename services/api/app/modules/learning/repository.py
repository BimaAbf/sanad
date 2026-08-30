"""All SQL for the mastery loop.

Two properties of this file are deliberate, and both cost something.

**The attempt history is read in full, not incrementally.** `load_history`
returns every attempt this child has made at the skills in question, and the
service folds BKT over all of them from the prior each time. An incremental
update would be cheaper and would make the stored `p_known` depend on how many
times the recompute has run rather than only on what the child did -- so a
replayed outbox, a retried request or a backfill would each leave a different
number in a clinical record. Recomputing is idempotent by construction: same
attempts in, same posterior out, however often it runs.

**Every transition writes a `mastery_events` row.** The database's backstop
against an AI verdict granting mastery is the `ai_cannot_grant` CHECK, and it
sits on that table rather than on `skill_states`. A transition that updated the
current state without recording the event would slip past the one constraint
P07 asked the database to enforce.
"""

from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

#: What a session touched. The loop recomputes only the skills this session
#: produced attempts for: a child has 88 skills and a session has a handful, and
#: re-folding the untouched ones is work whose result cannot differ.
SELECT_SESSION_TARGETS = text("""
    SELECT DISTINCT skill_id, modality::text AS modality
    FROM attempts
    WHERE session_id = :session_id
""")

#: `client_ts, id` rather than `client_ts` alone. Two attempts inside one second
#: are ordinary, and an unstable sort would let the fold's result depend on the
#: query planner. `id` is uuid v7, so it breaks the tie in arrival order.
SELECT_HISTORY = text("""
    SELECT skill_id,
           modality::text     AS modality,
           result::text       AS result,
           prompt_level::text AS prompt_level,
           choice_count,
           latency_ms,
           client_ts,
           -- Carried so the replay can reuse `tutor_ai`'s own deduplication
           -- rather than a second, differently-behaved one written here.
           idempotency_key
    FROM attempts
    WHERE child_id = :child_id AND skill_id IN :skill_ids
    ORDER BY client_ts, id
""").bindparams(bindparam("skill_ids", expanding=True))

SELECT_STATES = text("""
    SELECT skill_id, modality::text AS modality, state::text AS state,
           p_known, p_prior, interval_days, ease_factor, first_seen_at
    FROM skill_states
    WHERE child_id = :child_id AND skill_id IN :skill_ids
""").bindparams(bindparam("skill_ids", expanding=True))

#: The row is rewritten from the recomputed history rather than patched, for the
#: same reason the fold starts from the prior: a column left untouched by an
#: update is a column free to disagree with the attempts it summarises.
UPSERT_SKILL_STATE = text("""
    INSERT INTO skill_states (
        child_id, skill_id, modality, state, p_known, p_guess,
        interval_days, ease_factor, due_at, distinct_days, last_delayed_pass_at,
        consecutive_correct, total_attempts, total_correct, avg_latency_ms,
        first_seen_at, updated_at
    ) VALUES (
        :child_id, :skill_id, CAST(:modality AS modality),
        CAST(:state AS mastery_state), :p_known, :p_guess,
        :interval_days, :ease_factor, :due_at, :distinct_days,
        :last_delayed_pass_at, :consecutive_correct, :total_attempts,
        :total_correct, :avg_latency_ms, :first_seen_at, :now
    )
    ON CONFLICT (child_id, skill_id, modality) DO UPDATE SET
        state                = EXCLUDED.state,
        p_known              = EXCLUDED.p_known,
        p_guess              = EXCLUDED.p_guess,
        interval_days        = EXCLUDED.interval_days,
        ease_factor          = EXCLUDED.ease_factor,
        due_at               = EXCLUDED.due_at,
        distinct_days        = EXCLUDED.distinct_days,
        last_delayed_pass_at = EXCLUDED.last_delayed_pass_at,
        consecutive_correct  = EXCLUDED.consecutive_correct,
        total_attempts       = EXCLUDED.total_attempts,
        total_correct        = EXCLUDED.total_correct,
        avg_latency_ms       = EXCLUDED.avg_latency_ms,
        -- The FIRST first_seen_at wins. EXCLUDED would move it forward on every
        -- recompute and erase how long a child has been working on something,
        -- which is one of the few genuinely longitudinal facts here.
        first_seen_at        = COALESCE(skill_states.first_seen_at, EXCLUDED.first_seen_at),
        updated_at           = EXCLUDED.updated_at
""")

#: One row per transition. `rule_satisfied` is the DETERMINISTIC verdict and
#: never the AI's -- `ai_cannot_grant` checks exactly this column against
#: `to_state`, so writing an AI verdict here would disarm the constraint while
#: leaving it looking armed.
INSERT_MASTERY_EVENT = text("""
    INSERT INTO mastery_events (
        child_id, skill_id, modality, from_state, to_state,
        p_known_at_event, rule_satisfied, ai_verdict, ai_reason, session_id
    ) VALUES (
        :child_id, :skill_id, CAST(:modality AS modality),
        CAST(:from_state AS mastery_state), CAST(:to_state AS mastery_state),
        :p_known, :rule_satisfied, :ai_verdict, :ai_reason, :session_id
    )
""")

#: The decay sweep's working set. Only states that can decay: `not_started` has
#: nothing to forget, and a NULL `due_at` means no review was ever scheduled.
SELECT_OVERDUE_STATES = text("""
    SELECT child_id, skill_id, modality::text AS modality, state::text AS state,
           p_known, ease_factor, due_at
    FROM skill_states
    WHERE state <> 'not_started' AND due_at IS NOT NULL AND due_at < :now
    ORDER BY due_at
    LIMIT :limit
""")

#: Decay writes two columns and must not touch the other fifteen. It is not a
#: recompute from attempts and has no opinion about them.
UPDATE_DECAYED_STATE = text("""
    UPDATE skill_states
    SET p_known = :p_known, state = CAST(:state AS mastery_state), updated_at = :now
    WHERE child_id = :child_id AND skill_id = :skill_id
      AND modality = CAST(:modality AS modality)
""")


class LearningRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def session_targets(self, session_id: UUID) -> list[tuple[UUID, str]]:
        rows = await self._session.execute(SELECT_SESSION_TARGETS, {"session_id": session_id})
        return [(row.skill_id, str(row.modality)) for row in rows]

    async def load_history(self, *, child_id: UUID, skill_ids: list[UUID]) -> list[Any]:
        if not skill_ids:
            return []
        return list(
            await self._session.execute(
                SELECT_HISTORY, {"child_id": child_id, "skill_ids": skill_ids}
            )
        )

    async def load_states(self, *, child_id: UUID, skill_ids: list[UUID]) -> list[Any]:
        if not skill_ids:
            return []
        return list(
            await self._session.execute(
                SELECT_STATES, {"child_id": child_id, "skill_ids": skill_ids}
            )
        )

    async def upsert_state(self, values: dict[str, Any]) -> None:
        await self._session.execute(UPSERT_SKILL_STATE, values)

    async def record_mastery_event(self, values: dict[str, Any]) -> None:
        await self._session.execute(INSERT_MASTERY_EVENT, values)

    async def overdue_states(self, *, now: dt.datetime, limit: int) -> list[Any]:
        return list(
            await self._session.execute(SELECT_OVERDUE_STATES, {"now": now, "limit": limit})
        )

    async def apply_decay(self, values: dict[str, Any]) -> None:
        await self._session.execute(UPDATE_DECAYED_STATE, values)


__all__ = ["LearningRepository"]
