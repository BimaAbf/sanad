"""Widen `skill_states`' primary key to (child_id, skill_id, modality).

**This is the project's first deliberately destructive migration, and it is
alone in this revision on purpose.** GUARD 5's failure message says to split an
additive step from a destructive one; 0011 is the additive half and this is the
other. Shipping it needs the `destructive-migration` label and the manual
approval docs/08 §4 requires.

### Why it cannot be avoided

docs/02 §6 keys this table on `(child_id, skill_id, modality)`. 0008 keyed it on
`(child_id, skill_id)`. A narrower key is not a smaller version of the right
one — it makes the right one unrepresentable: a child cannot hold a receptive
state and an expressive state for the same skill at once.

That has not bitten yet only because the expressive path is the voice tier and
the voice tier has no client. Every other table already threads modality
through: `attempts.modality`, `mastery_events.modality`, and the
`(skill_id, modality)` keys `tutor_ai/session.py` has used since P08. This
table is the one place the concept goes missing, and the first expressive
attempt ever recorded would collide with the receptive row.

### Why now rather than later

There are twelve rows in this table on the only database it has ever existed
on, and all twelve were written by `sanad rag demo`. Nothing has been deployed.
The cost of this change is monotonically increasing from here and it will never
again be as close to zero as it is today.

### What an operator should know

Between the DROP and the ADD the table has no primary key. Both statements are
in one transaction, so no other session observes that window. `ADD PRIMARY KEY`
takes an ACCESS EXCLUSIVE lock and builds a unique index; on a table of any real
size that blocks reads and writes for the duration, and the concurrent form
(`CREATE UNIQUE INDEX CONCURRENTLY` then `ADD CONSTRAINT ... USING INDEX`) is
the shape to reach for instead. At twelve rows it is instant, and stating the
condition is cheaper than discovering it.

Revision ID: 0012_skill_states_modality_key
Revises: 0011_skill_states_columns
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0012_skill_states_modality_key"
down_revision: str | None = "0011_skill_states_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE skill_states DROP CONSTRAINT skill_states_pkey")
    op.execute("ALTER TABLE skill_states ADD PRIMARY KEY (child_id, skill_id, modality)")


def downgrade() -> None:
    # Only reversible while no skill has two modalities. If one does, the
    # narrow key cannot hold the data and this fails loudly, which is correct:
    # silently discarding an expressive record to fit an old schema would be
    # the worst available outcome.
    op.execute("ALTER TABLE skill_states DROP CONSTRAINT skill_states_pkey")
    op.execute("ALTER TABLE skill_states ADD PRIMARY KEY (child_id, skill_id)")
