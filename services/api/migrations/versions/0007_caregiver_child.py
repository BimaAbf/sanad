"""The caregiver_child link table, omitted from 0003.

DDL transcribed from docs/02-data-model.md §3, verbatim. Nothing here is new
design — the table has been specified since the architecture package, and
`app.modules.identity.models.CaregiverChild` has always mapped it.

WHAT HAPPENED, because it is worth recording rather than quietly fixing.

`0003_children_consent` creates `children`, `consent_definitions`, `consents`
and `caregiver_invites`, and its own comment reads:

    # Co-caregiver invites. Not in docs/02 §3 — the DDL there has caregiver_child
    # but nowhere to hold a pending invitation ...

— so the author had read the `caregiver_child` DDL, referred to it in prose, and
then never wrote the `CREATE TABLE`. Everything downstream assumed it existed:
the model, `children/repository.py`, `identity/repository.py`, and the ownership
check on every child-scoped route.

It went unnoticed because the Docker daemon was down for the entire build, so
`0002`–`0006` had never executed and `repository.py` sat at ~34% coverage with
every SQL path unreachable. BLOCKED.md #1 predicted exactly this:

    I would not trust the DDL in 0002–0004 until that has run. They are
    transcribed from docs/02 and reviewed, but transcription errors in DDL are
    exactly what a first migration run catches.

The first end-to-end request after the daemon came back — `POST /children` —
returned 500 with `relation "caregiver_child" does not exist`.

Written as a new forward migration rather than an edit to `0003`, because a
migration that has been applied anywhere is history: editing it silently
diverges every database that already ran it. `0007` is additive, so the
destructive-migration guard passes without a labelled PR.

Revision ID: 0007_caregiver_child
Revises: 0006_notifications
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007_caregiver_child"
down_revision: str | None = "0006_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # `IF NOT EXISTS` so this is safe on a database built from a corrected 0003
    # in some future rebuild, as well as on one that ran 0003 as shipped.
    op.execute("""
        CREATE TABLE IF NOT EXISTS caregiver_child (
            caregiver_id  uuid NOT NULL REFERENCES caregivers(id) ON DELETE CASCADE,
            child_id      uuid NOT NULL REFERENCES children(id)   ON DELETE CASCADE,
            role          caregiver_role NOT NULL DEFAULT 'owner',
            invited_by    uuid REFERENCES caregivers(id),
            accepted_at   timestamptz,
            created_at    timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (caregiver_id, child_id)
        )
    """)
    # docs/02 §3 indexes child_id. The primary key already covers
    # (caregiver_id, child_id), so lookups the other way -- "who else cares for
    # this child", which every co-caregiver and erasure path runs -- would
    # otherwise be a sequential scan.
    op.execute("CREATE INDEX IF NOT EXISTS ix_caregiver_child_child ON caregiver_child (child_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS caregiver_child")
