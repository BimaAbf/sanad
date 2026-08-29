"""The skills catalogue and per-child mastery state.

`progress/repository.py::SELECT_SKILL_CARDS` has joined `skills` to
`skill_states` since P10. Neither table has ever existed: the query was written
against docs/02 §10 and the migration that should have created them was never
authored, so `GET /children/{id}/progress/skills` was a guaranteed
`relation "skills" does not exist` in any running instance.

That is the same defect class as `caregiver_child` in 0007 and it survived for
the same reason -- `repository.py` had no database to run against, so 863
passing tests could not see it.

Column set transcribed from two places that already fix it, not invented here:
the SELECT list of `SELECT_SKILL_CARDS` (skill_id, code, label_ar, category,
state, p_known, due_at, updated_at) and the `Skill` dataclass in
`seeds/curriculum.py`, which is what `sanad seed` loads.

Additive only. Both enums (`skill_category`, `mastery_state`) come from 0001.

Revision ID: 0008_skills_states
Revises: 0007_caregiver_child
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008_skills_states"
down_revision: str | None = "0007_caregiver_child"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE skills (
            id                uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            code              text NOT NULL UNIQUE,
            category          skill_category NOT NULL,
            label_ar          text NOT NULL,
            label_vowelised   text NOT NULL,
            label_egy         text NOT NULL,
            transliteration   text NOT NULL,
            phonemes          text NOT NULL,
            difficulty_tier   smallint NOT NULL,
            intro_order       integer NOT NULL,
            alt_text_ar       text NOT NULL,
            -- (L, a, b)-ish triple for the tier-1 contrast rule; NULL for every
            -- non-colour skill, which is most of them.
            colour            jsonb,
            distractor_pool   jsonb NOT NULL DEFAULT '[]'::jsonb,
            prerequisites     jsonb NOT NULL DEFAULT '[]'::jsonb,
            is_active         boolean NOT NULL DEFAULT true,
            created_at        timestamptz NOT NULL DEFAULT now(),
            updated_at        timestamptz NOT NULL DEFAULT now()
        )
    """)
    # The catalogue is read in `intro_order` within `category` on every skills
    # page render, and filtered on `is_active` every time.
    op.execute("CREATE INDEX skills_active_order_idx ON skills (category, intro_order) "
               "WHERE is_active")

    op.execute("""
        CREATE TABLE skill_states (
            child_id    uuid NOT NULL REFERENCES children(id) ON DELETE CASCADE,
            skill_id    uuid NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
            state       mastery_state NOT NULL DEFAULT 'not_started',
            -- BKT posterior. Never rendered to a caregiver as a percentage;
            -- docs/04a forbids it and a test asserts it over the whole schema.
            p_known     double precision NOT NULL DEFAULT 0.0
                        CHECK (p_known >= 0.0 AND p_known <= 1.0),
            due_at      timestamptz,
            updated_at  timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (child_id, skill_id)
        )
    """)
    # The erasure walk deletes by child; the primary key leads on child_id, so
    # that is already covered. This one serves the due-review sweep.
    op.execute("CREATE INDEX skill_states_due_idx ON skill_states (due_at) "
               "WHERE due_at IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS skill_states")
    op.execute("DROP TABLE IF EXISTS skills")
