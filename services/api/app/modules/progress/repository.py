"""SQL for events, rollups and the dashboard reads.

Every rollup write is an upsert keyed on `(child_id, period)`, which is what
makes replaying a job a no-op at the database level rather than in application
code. docs/04a §C09 asks for exactly that.

Partition management lives here too: `events` is RANGE-partitioned monthly
(docs/02 §9) and a partition that does not exist is an insert that fails. The
creation job therefore runs *ahead* of need, not at the boundary.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.progress.domain.periods import month_key, next_month, partition_bounds
from app.modules.progress.domain.rollup import Rollup

logger = structlog.get_logger(__name__)

#: How far ahead partitions are created. Two months means a job that fails
#: silently for four weeks still does not cause a failed insert.
PARTITION_LOOKAHEAD_MONTHS = 2

UPSERT_ROLLUP = text("""
    INSERT INTO progress_rollups (
        child_id, period, sessions, minutes, attempts, accuracy,
        skills_mastered, skills_practising, by_category, updated_at
    ) VALUES (
        :child_id, :period, :sessions, :minutes, :attempts, :accuracy,
        :skills_mastered, :skills_practising, CAST(:by_category AS jsonb), now()
    )
    ON CONFLICT (child_id, period) DO UPDATE SET
        sessions          = EXCLUDED.sessions,
        minutes           = EXCLUDED.minutes,
        attempts          = EXCLUDED.attempts,
        accuracy          = EXCLUDED.accuracy,
        skills_mastered   = EXCLUDED.skills_mastered,
        skills_practising = EXCLUDED.skills_practising,
        by_category       = EXCLUDED.by_category,
        updated_at        = now()
""")

#: `ON CONFLICT DO NOTHING` on the idempotency key is what makes an outbox
#: drain safe. The client may replay the same batch as often as it likes.
INSERT_EVENT = text("""
    INSERT INTO events (child_id, caregiver_id, name, props, client_ts, idempotency_key)
    VALUES (:child_id, :caregiver_id, :name, CAST(:props AS jsonb), :client_ts, :idempotency_key)
    ON CONFLICT (idempotency_key, client_ts) DO NOTHING
""")

SELECT_ROLLUPS = text("""
    SELECT child_id, period, sessions, minutes, attempts, accuracy,
           skills_mastered, skills_practising, by_category
    FROM progress_rollups
    WHERE child_id = :child_id AND period LIKE :pattern
    ORDER BY period
""")

SELECT_SKILL_CARDS = text("""
    SELECT s.id AS skill_id, s.code, s.label_ar, s.category,
           st.state, st.p_known, st.due_at, st.updated_at AS last_seen_at
    FROM skills s
    LEFT JOIN skill_states st
           ON st.skill_id = s.id AND st.child_id = :child_id
    WHERE s.is_active
    ORDER BY s.category, s.code
""")


class ProgressRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_events(self, rows: Sequence[dict[str, object]]) -> int:
        """Returns the number actually inserted; the rest were duplicates."""
        inserted = 0
        for row in rows:
            result = await self._session.execute(INSERT_EVENT, row)
            # ON CONFLICT DO NOTHING reports 0 rows for a replayed event, which
            # is exactly the count the caller reports back as `duplicates`.
            inserted += int(getattr(result, "rowcount", 0) or 0)
        return inserted

    async def upsert_rollups(self, rollups: Sequence[Rollup]) -> None:
        import json

        for rollup in rollups:
            await self._session.execute(
                UPSERT_ROLLUP,
                {
                    "child_id": rollup.child_id,
                    "period": rollup.period,
                    "sessions": rollup.sessions,
                    "minutes": rollup.minutes,
                    "attempts": rollup.attempts,
                    "accuracy": rollup.accuracy,
                    "skills_mastered": rollup.skills_mastered,
                    "skills_practising": rollup.skills_practising,
                    "by_category": json.dumps(rollup.by_category, ensure_ascii=False),
                },
            )

    async def rollups(self, child_id: str, *, pattern: str = "%") -> list[dict[str, object]]:
        rows = await self._session.execute(
            SELECT_ROLLUPS, {"child_id": child_id, "pattern": pattern}
        )
        return [dict(row._mapping) for row in rows]

    async def skill_cards(self, child_id: str) -> list[dict[str, object]]:
        rows = await self._session.execute(SELECT_SKILL_CARDS, {"child_id": child_id})
        return [dict(row._mapping) for row in rows]

    async def ensure_partitions(self, *, today: dt.date) -> list[str]:
        """Create this month's partition and the next N. Idempotent.

        `IF NOT EXISTS` rather than a catalogue query: two workers running the
        nightly job at the same time is normal, and a race here would page
        someone at 02:00 for nothing.
        """
        created: list[str] = []
        cursor = today.replace(day=1)
        for _ in range(PARTITION_LOOKAHEAD_MONTHS + 1):
            start, end = partition_bounds(cursor)
            name = f"events_{month_key(cursor)}"
            await self._session.execute(
                text(
                    f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF events "
                    f"FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}')"
                )
            )
            created.append(name)
            cursor = next_month(cursor)
        logger.info("event_partitions_ensured", partitions=len(created))
        return created
