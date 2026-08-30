"""A monotonic version counter on children, for optimistic concurrency.

NOT in docs/02 §3. docs/04a §C02 specifies optimistic concurrency via
`updated_at` in an `If-Unmodified-Since` header, and that cannot actually work:
HTTP-date headers have WHOLE-SECOND resolution, so two PATCHes landing in the
same second both see an unchanged timestamp and both succeed. That is precisely
the lost update the mechanism exists to prevent, and it was caught by a test
that performs two writes in the same second.

The header stays supported as the documented interface. The authoritative check
is now this counter, surfaced as an `ETag` and accepted as `If-Match`. See
docs/adr/003-consent-model.md.

Revision ID: 0004_child_version
Revises: 0003_children_consent
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_child_version"
down_revision: str | None = "0003_children_consent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE children ADD COLUMN version integer NOT NULL DEFAULT 1")


def downgrade() -> None:
    op.execute("ALTER TABLE children DROP COLUMN IF EXISTS version")
