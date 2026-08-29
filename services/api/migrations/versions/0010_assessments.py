"""The assessments tables. Without them the engine cannot persist anything.

`assessment/` has been domain logic only since P04: an engine that can replay a
sequence of answers, and nowhere to keep the sequence. The visible consequence
was `progress/history.py::assessment_points` returning `[]` unconditionally --
documented as honest, and it was -- so `GET /children/{id}/progress/journey`
answered `insufficient_data` forever, for every child, no matter how many
assessments a family completed.

Two tables, and the second one's shape is the whole design:

**`assessment_answers` is append-only.** A correction is a new row with the
previous one stamped `superseded_at`, never an UPDATE. That is what makes
`engine.replay()` exact: the surviving sequence, in order, replayed from the
entry band, reproduces basal and ceiling exactly rather than approximately. The
same reason `consents` is append-only in 0003.

`domain_da` is denormalised onto `assessments` at finalisation rather than
recomputed on every journey render. The journey chart reads three to six rows
per child; replaying six assessments of ~600 items each on a dashboard GET would
be the slowest thing in the product for a number that cannot change once the
assessment is completed.

`item_id` is text, not a FK: there is no `assessment_items` table -- the bank is
`seeds/item_bank.py`, a generated placeholder pending open decision O1 -- and
blocking persistence on the licensed bank would mean no assessment history at
all. `bank_version` on the parent row is what makes an old answer set
interpretable after the bank changes; `engine.replay()` already skips an item
the current bank does not contain.

Additive only. Both enums (`assessment_status`, `response_verdict`,
`response_source`) come from 0001.

Revision ID: 0010_assessments
Revises: 0010_chat_decision_points

Rebased from 0009 onto 0010_chat_decision_points, which was authored in
parallel and landed on the same parent. Two heads make `alembic upgrade head`
an error for everyone. This file was unapplied in every database and the other
was already applied, so the unapplied one moves -- the same rule as a git
rebase. Nothing in the DDL below changed.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0010_assessments"
down_revision: str | None = "0010_chat_decision_points"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS assessments (
            id              uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            child_id        uuid NOT NULL REFERENCES children(id) ON DELETE CASCADE,
            started_by      uuid NOT NULL REFERENCES caregivers(id),
            -- Pinned at creation. An answer set is only interpretable against
            -- the bank it was administered with.
            bank_version    text NOT NULL,
            -- CORRECTED age at administration, in months (docs/04a C02). Stored
            -- rather than derived: entry bands used this value, so a replay two
            -- years later must use it too, not today's age.
            child_months    double precision NOT NULL,
            status          assessment_status NOT NULL DEFAULT 'in_progress',
            -- domain code -> developmental age in months. Written once, at
            -- finalisation. Not a quotient and not a percentile: docs/04a
            -- forbids either reaching a dashboard.
            domain_da       jsonb NOT NULL DEFAULT '{}'::jsonb,
            skills_mastered smallint NOT NULL DEFAULT 0,
            started_at      timestamptz NOT NULL DEFAULT now(),
            completed_at    timestamptz,
            updated_at      timestamptz NOT NULL DEFAULT now()
        )
    """)
    # The journey reads every completed assessment for one child, newest last.
    op.execute(
        "CREATE INDEX IF NOT EXISTS assessments_child_started ON assessments (child_id, started_at)"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS assessment_answers (
            id              uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            assessment_id   uuid NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
            item_id         text NOT NULL,
            verdict         response_verdict NOT NULL,
            source          response_source NOT NULL DEFAULT 'caregiver_tap',
            -- True for an answer the engine inferred rather than observed.
            -- `engine.replay` needs it: propagated evidence does not extend a
            -- basal or ceiling run the same way an observed answer does.
            propagated      boolean NOT NULL DEFAULT false,
            -- Administration order. Replay is ordered by this, never by a
            -- timestamp: two answers written in the same millisecond during an
            -- evidence-propagation cascade must still replay in one order.
            sequence        integer NOT NULL,
            -- Set when a correction supersedes this row. Never deleted.
            superseded_at   timestamptz,
            idempotency_key text,
            created_at      timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS assessment_answers_replay "
        "ON assessment_answers (assessment_id, sequence)"
    )
    # The client retries an answer POST after a dropped connection; without this
    # the retry is a second answer and the ceiling moves. Partial, because a
    # propagated answer is written by the server and carries no client key.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS assessment_answers_idempotency "
        "ON assessment_answers (assessment_id, idempotency_key) "
        "WHERE idempotency_key IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS assessment_answers")
    op.execute("DROP TABLE IF EXISTS assessments")
