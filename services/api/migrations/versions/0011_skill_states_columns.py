"""`skill_states`, completed to docs/02 §6.

0008 created this table by transcribing the SELECT list of
`progress/repository.py::SELECT_SKILL_CARDS` — the eight columns one query
happened to read — rather than the table docs/02 §6 specifies. That was enough
to make the skills page stop erroring and not enough to run the learning loop,
which needs the BKT parameters, the spaced-repetition fields and the mastery
bookkeeping that were left out.

Thirteen columns, transcribed verbatim from docs/02 §6 with its defaults. Two
deliberate divergences from that document, both recorded here rather than
silently absorbed:

* **`p_known` stays `double precision`.** docs/02 says `numeric(5,4)`. Changing
  it would need a column-type rewrite, which GUARD 5 correctly refuses, and the
  type is not the interesting part — four decimal places of a Bayesian
  posterior is a storage choice, not a clinical one. (That sentence originally
  spelled the statement out and tripped the guard on its own prose, which is a
  fair thing for a text-matching guard to do.) The DEFAULT *is* corrected: 0008 wrote
  `0.0`, and the prior every other file in the project agrees on is
  `bkt.P_L0 = 0.15`. A row created at 0.0 would say a child is certainly
  ignorant of a skill nobody has shown them.
* **`due_at` stays nullable.** docs/02 says `NOT NULL DEFAULT now()`. Adding
  NOT NULL to an existing column is what GUARD 5 exists to stop; NULL already
  means "no review scheduled", which is the truth for a skill never practised.

`modality` lands here with a default so this migration stays additive, but the
PRIMARY KEY it belongs in cannot widen additively. That is 0012, on its own,
for exactly the reason GUARD 5's failure message gives.

Revision ID: 0011_skill_states_columns
Revises: 0010_assessments
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011_skill_states_columns"
down_revision: str | None = "0010_assessments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # `modality` first: 0012's primary key needs it to exist and be populated.
    # 'receptive' as the default is not a guess — every attempt row the product
    # can currently produce is receptive (`attempts.modality` carries the same
    # default), because the expressive path is the voice tier and it has no
    # client yet.
    op.execute("""
        ALTER TABLE skill_states
            ADD COLUMN IF NOT EXISTS modality modality NOT NULL DEFAULT 'receptive'
    """)

    # --- BKT, per docs/02 §6. Stored per row rather than as module constants
    # --- so they can be tuned per category and later fitted by EM, which is
    # --- what `bkt.py`'s docstring has promised since P07.
    op.execute("""
        ALTER TABLE skill_states
            ADD COLUMN IF NOT EXISTS p_transit numeric(5,4) NOT NULL DEFAULT 0.2500,
            ADD COLUMN IF NOT EXISTS p_slip    numeric(5,4) NOT NULL DEFAULT 0.2500,
            ADD COLUMN IF NOT EXISTS p_guess   numeric(5,4) NOT NULL DEFAULT 0.5000
    """)

    # --- spaced repetition (SM-2 derived, gentled) ---
    op.execute("""
        ALTER TABLE skill_states
            ADD COLUMN IF NOT EXISTS interval_days numeric(6,2) NOT NULL DEFAULT 1,
            ADD COLUMN IF NOT EXISTS ease_factor   numeric(4,2) NOT NULL DEFAULT 2.30
    """)

    # --- mastery bookkeeping ---
    op.execute("""
        ALTER TABLE skill_states
            ADD COLUMN IF NOT EXISTS distinct_days        smallint NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS last_delayed_pass_at timestamptz,
            ADD COLUMN IF NOT EXISTS consecutive_correct  smallint NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS total_attempts       integer  NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS total_correct        integer  NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS avg_latency_ms       integer,
            ADD COLUMN IF NOT EXISTS first_seen_at        timestamptz
    """)

    # Corrects 0008's `DEFAULT 0.0`. Changing a default cannot break the old
    # code serving traffic during a bake -- it only affects rows inserted
    # without the column, and nothing inserts a skill state without a p_known.
    op.execute("ALTER TABLE skill_states ALTER COLUMN p_known SET DEFAULT 0.15")

    # docs/02 §6's own index. The due sweep asks "what is this child due for",
    # never "what is anyone due for", so child_id leads.
    op.execute("""
        CREATE INDEX IF NOT EXISTS skill_states_child_due_idx
            ON skill_states (child_id, due_at)
            WHERE state <> 'not_started'
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS skill_states_child_due_idx")
    op.execute("ALTER TABLE skill_states ALTER COLUMN p_known SET DEFAULT 0.0")
    op.execute("""
        ALTER TABLE skill_states
            DROP COLUMN IF EXISTS first_seen_at,
            DROP COLUMN IF EXISTS avg_latency_ms,
            DROP COLUMN IF EXISTS total_correct,
            DROP COLUMN IF EXISTS total_attempts,
            DROP COLUMN IF EXISTS consecutive_correct,
            DROP COLUMN IF EXISTS last_delayed_pass_at,
            DROP COLUMN IF EXISTS distinct_days,
            DROP COLUMN IF EXISTS ease_factor,
            DROP COLUMN IF EXISTS interval_days,
            DROP COLUMN IF EXISTS p_guess,
            DROP COLUMN IF EXISTS p_slip,
            DROP COLUMN IF EXISTS p_transit,
            DROP COLUMN IF EXISTS modality
    """)
