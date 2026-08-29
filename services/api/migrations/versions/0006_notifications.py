"""Notifications, caregiver notification preferences and the dedupe index.

DDL transcribed from docs/02-data-model.md §8, plus one addition:
`caregiver_notification_prefs`. docs/04a §C10 requires a one-tap "fewer
reminders" control that sets a per-caregiver 1/week cap, and there is nowhere in
docs/02 for that flag to live.

The UNIQUE index on `dedupe_key` is the whole anti-double-send mechanism. It is
enforced by the DATABASE and not by application code, because two ARQ workers
running the same cron minute is normal operation, and a read-then-write check
lets both through.

Revision ID: 0006_notifications
Revises: 0005_events_rollups
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006_notifications"
down_revision: str | None = "0005_events_rollups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE notifications (
            id            uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            caregiver_id  uuid NOT NULL REFERENCES caregivers(id) ON DELETE CASCADE,
            child_id      uuid REFERENCES children(id) ON DELETE CASCADE,
            kind          text NOT NULL,
            payload       jsonb NOT NULL DEFAULT '{}',
            body_ar       text NOT NULL,
            channel       text NOT NULL,
            scheduled_for timestamptz NOT NULL,
            sent_at       timestamptz,
            read_at       timestamptz,
            dedupe_key    text NOT NULL,
            created_at    timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT notifications_channel_shape
                CHECK (channel IN ('push', 'sms', 'in_app')),
            CONSTRAINT notifications_kind_shape
                CHECK (kind IN ('pgee_due', 'weekly_digest', 'report_ready',
                                'escalation_ack', 'streak'))
        )
    """)
    # NOT NULL + UNIQUE rather than the nullable UNIQUE in docs/02 §8: a
    # nullable unique column lets any number of NULL rows through, which would
    # make the dedupe guarantee vacuous for exactly the jobs that forgot to set
    # a key. Every send path builds one (policy.dedupe_key), so NOT NULL costs
    # nothing and closes the hole.
    op.execute("CREATE UNIQUE INDEX notifications_dedupe_uq ON notifications (dedupe_key)")
    op.execute(
        "CREATE INDEX notifications_pending ON notifications (scheduled_for) WHERE sent_at IS NULL"
    )
    op.execute(
        "CREATE INDEX notifications_caregiver_sent ON notifications (caregiver_id, sent_at DESC)"
    )

    op.execute("""
        CREATE TABLE caregiver_notification_prefs (
            caregiver_id    uuid PRIMARY KEY
                            REFERENCES caregivers(id) ON DELETE CASCADE,
            fewer_reminders boolean NOT NULL DEFAULT false,
            streak_opt_in   boolean NOT NULL DEFAULT false,
            push_endpoint   text,
            push_p256dh     text,
            push_auth       text,
            ignored_pushes  smallint NOT NULL DEFAULT 0,
            updated_at      timestamptz NOT NULL DEFAULT now()
        )
    """)

    # `pgee_due` is capped at three nudges EVER per assessment cycle
    # (docs/04a §C10). That count has to survive notification pruning, so it
    # lives on its own row rather than being derived from notifications.
    op.execute("""
        CREATE TABLE pgee_nudge_state (
            child_id     uuid PRIMARY KEY REFERENCES children(id) ON DELETE CASCADE,
            cycle_start  timestamptz NOT NULL,
            nudges_sent  smallint NOT NULL DEFAULT 0,
            updated_at   timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pgee_nudges_never_exceed_three CHECK (nudges_sent <= 3)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pgee_nudge_state")
    op.execute("DROP TABLE IF EXISTS caregiver_notification_prefs")
    op.execute("DROP TABLE IF EXISTS notifications")
