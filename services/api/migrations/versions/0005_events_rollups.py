"""Events (monthly RANGE partitions) and progress_rollups.

DDL transcribed from docs/02-data-model.md §8, with two additions that the
document does not spell out and the acceptance criteria require:

1. `events.idempotency_key`. docs/05 §5 has the client drain an offline outbox
   into POST /events, which means the same batch arrives more than once by
   design. Without a key the server cannot tell a replay from a real repeat.
   The unique index includes `client_ts` because a partitioned table's unique
   index must contain the partition key — Postgres refuses otherwise, and that
   refusal is the reason the column pair is what it is rather than the key alone.

2. The initial partitions. A RANGE-partitioned table with no partition rejects
   every insert, so the migration creates the current month plus two ahead and
   the nightly job keeps the window rolling.

Revision ID: 0005_events_rollups
Revises: 0004_child_version
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

from alembic import op

revision: str = "0005_events_rollups"
down_revision: str | None = "0004_child_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LOOKAHEAD_MONTHS = 3


def _month_starts(count: int) -> list[tuple[dt.date, dt.date]]:
    today = dt.datetime.now(dt.UTC).date().replace(day=1)
    bounds: list[tuple[dt.date, dt.date]] = []
    cursor = today
    for _ in range(count):
        nxt = (
            dt.date(cursor.year + 1, 1, 1)
            if cursor.month == 12
            else dt.date(cursor.year, cursor.month + 1, 1)
        )
        bounds.append((cursor, nxt))
        cursor = nxt
    return bounds


def upgrade() -> None:
    op.execute("""
        CREATE TABLE events (
            id              bigserial,
            child_id        uuid,
            caregiver_id    uuid,
            name            text NOT NULL,
            props           jsonb NOT NULL DEFAULT '{}',
            client_ts       timestamptz,
            server_ts       timestamptz NOT NULL DEFAULT now(),
            idempotency_key text NOT NULL
        ) PARTITION BY RANGE (server_ts)
    """)
    # The partition key must be part of every unique index on a partitioned
    # table. server_ts defaults to now(), so the pair is effectively the key.
    op.execute("""
        CREATE UNIQUE INDEX events_idempotency_uq
            ON events (idempotency_key, server_ts)
    """)
    op.execute("CREATE INDEX events_child_ts ON events (child_id, server_ts DESC)")
    op.execute("CREATE INDEX events_name_ts ON events (name, server_ts DESC)")

    for start, end in _month_starts(LOOKAHEAD_MONTHS):
        name = f"events_{start.year:04d}_{start.month:02d}"
        op.execute(
            f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF events "
            f"FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}')"
        )

    op.execute("""
        CREATE TABLE progress_rollups (
            child_id          uuid NOT NULL REFERENCES children(id) ON DELETE CASCADE,
            period            text NOT NULL,
            sessions          integer NOT NULL DEFAULT 0,
            minutes           integer NOT NULL DEFAULT 0,
            attempts          integer NOT NULL DEFAULT 0,
            accuracy          numeric(4,3),
            skills_mastered   integer NOT NULL DEFAULT 0,
            skills_practising integer NOT NULL DEFAULT 0,
            by_category       jsonb NOT NULL DEFAULT '{}',
            updated_at        timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (child_id, period),
            CONSTRAINT progress_rollups_period_shape
                CHECK (period = 'all' OR period LIKE 'day:%' OR period LIKE 'week:%')
        )
    """)
    op.execute("CREATE INDEX progress_rollups_child_period ON progress_rollups (child_id, period)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS progress_rollups")
    op.execute("DROP TABLE IF EXISTS events CASCADE")
