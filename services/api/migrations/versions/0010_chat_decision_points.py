"""The two `ai_decision_point` values the chat surfaces need.

**Why this is its own revision rather than part of 0009.** It was in 0009
first, and that was wrong for a reason worth recording: a database that had
already applied 0009 would never re-run it, so the enum values would exist on
every fresh database and on none of the existing ones. Alembic revisions are
applied once; anything added to a revision after it has shipped is a change
nobody receives. That failure is silent -- `alembic current` reads `head` and
the values are simply absent -- and it was found here by checking `pg_enum`
after the fact rather than by trusting the migration to have done what it said.

`ai_calls` (docs/02 §7) does not exist yet, so nothing reads these values today.
They are added anyway because the enum is the contract, and a decision point
that ships before its enum value means the first `ai_calls` insert fails in
production rather than in CI.

`caregiver_chat` produces prose a parent reads about their own child;
`child_chat` selects one id from the closed set of reviewed phrases in
`chat/domain.py`. Their required guardrail layers are registered in
`app/guardrails/chain.py` and enforced by
`tools/guards/required_guardrail_layer.py`.

Additive. `ADD VALUE IF NOT EXISTS` is transactional on PG12+, and neither value
is *used* in this transaction, which is the case the older restriction existed
for.

Revision ID: 0010_chat_decision_points
Revises: 0009_recommendation_chat
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0010_chat_decision_points"
down_revision: str | None = "0009_recommendation_chat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_DECISION_POINTS: tuple[str, ...] = ("caregiver_chat", "child_chat")


def upgrade() -> None:
    for value in NEW_DECISION_POINTS:
        op.execute(f"ALTER TYPE ai_decision_point ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    """No-op, and not a lazy one.

    Postgres cannot remove a value from an enum. The only way back is to drop
    and recreate the type, which is destructive, would need every dependent
    column rewritten, and is refused by
    `tools/guards/destructive_migration.py`. docs/08 §4 makes migrations
    forward-only for exactly this class of change, so the honest downgrade is
    to leave two unused labels in place.
    """
