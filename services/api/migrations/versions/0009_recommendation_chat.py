"""Play history, the retrieval index and the chat transcript.

Three groups of tables, and the first group is the reason the other two are
worth anything.

**`play_sessions`, `attempts`, `mastery_events`** are docs/02 §6, transcribed.
They have never existed. Until now the only durable record of what a child did
was `events` -- first-party telemetry, one `session_end` row per session
carrying totals -- which is enough to draw a streak and nothing else. Retrieval
over "the user history" needs the per-attempt record: which activity, which
wrong choice they tapped, at what prompt rung, how long they took. That is what
`attempts` holds and what makes a confusion pattern computable at all.

**`child_memory`** is the retrieval index. One row per built document
(`recommendation/documents.py`), embedded with `recommendation/embedding.py`.
Note the width comes from `EMBEDDING_DIM` rather than a literal: the module and
the column have to agree or every insert fails at runtime, and importing the
name is the only way to make that impossible to get wrong.

**`chat_messages`** is the caregiver/child transcript. Retention is deliberately
short and stated in the column comment rather than left to a runbook.

The two new `ai_decision_point` values the chat surfaces need are in 0010,
not here -- see that file for why they had to be a separate revision.

`ai_cannot_grant` is carried over from docs/02 §6 verbatim. It is principle P2
enforced by the database: even a bug in application code cannot let an AI
verdict promote a child to `mastered` without the deterministic rule being
satisfied. P07 has wanted this constraint to exist against a real database since
it was written.

Additive only. Every enum used here comes from 0001.

Revision ID: 0009_recommendation_chat
Revises: 0008_skills_states
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.modules.recommendation.embedding import EMBEDDING_DIM

revision: str = "0009_recommendation_chat"
down_revision: str | None = "0008_skills_states"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- play history (docs/02 §6) -----------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS play_sessions (
            id                uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            child_id          uuid NOT NULL REFERENCES children(id) ON DELETE CASCADE,
            started_by        uuid NOT NULL REFERENCES caregivers(id),
            plan              jsonb NOT NULL DEFAULT '[]'::jsonb,
            plan_source       text  NOT NULL DEFAULT 'deterministic_fallback',
            graph_checkpoint  jsonb,
            activities_done   smallint NOT NULL DEFAULT 0,
            correct_count     smallint NOT NULL DEFAULT 0,
            ended_reason      text,
            summary_ar        text,
            started_at        timestamptz NOT NULL DEFAULT now(),
            ended_at          timestamptz,
            CONSTRAINT play_sessions_plan_source
                CHECK (plan_source IN ('ai', 'deterministic_fallback'))
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS play_sessions_child_started "
        "ON play_sessions (child_id, started_at DESC)"
    )

    # `activity_id` is a plain text code rather than a FK: there is no
    # `activities` table yet (docs/02 §5 is unmigrated), and blocking the
    # per-attempt record on the content catalogue would mean no history at all.
    # The code shape is `<kind>:<skill code>`, the same one `progress/history.py`
    # already produces.
    op.execute("""
        CREATE TABLE IF NOT EXISTS attempts (
            id                uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            session_id        uuid NOT NULL REFERENCES play_sessions(id) ON DELETE CASCADE,
            child_id          uuid NOT NULL REFERENCES children(id) ON DELETE CASCADE,
            activity_code     text NOT NULL,
            skill_id          uuid NOT NULL REFERENCES skills(id),
            modality          modality NOT NULL DEFAULT 'receptive',
            attempt_no        smallint NOT NULL DEFAULT 1,
            result            attempt_result NOT NULL,
            prompt_level      prompt_level NOT NULL DEFAULT 'independent',
            latency_ms        integer,
            choice_count      smallint NOT NULL DEFAULT 2,
            selected_skill_id uuid REFERENCES skills(id),
            asr_heard         text,
            asr_similarity    numeric(4,3),
            asr_provider      text,
            client_ts         timestamptz NOT NULL DEFAULT now(),
            created_at        timestamptz NOT NULL DEFAULT now(),
            idempotency_key   text NOT NULL UNIQUE
        )
    """)
    # The confusion query groups by (skill_id, selected_skill_id) for one child
    # over a recent window; the mastery window reads the last N for one skill.
    # Both are covered by this one index.
    op.execute(
        "CREATE INDEX IF NOT EXISTS attempts_child_skill_created "
        "ON attempts (child_id, skill_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS attempts_session_created "
        "ON attempts (session_id, created_at)"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS mastery_events (
            id               uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            child_id         uuid NOT NULL REFERENCES children(id) ON DELETE CASCADE,
            skill_id         uuid NOT NULL REFERENCES skills(id),
            modality         modality NOT NULL DEFAULT 'receptive',
            from_state       mastery_state NOT NULL,
            to_state         mastery_state NOT NULL,
            p_known_at_event numeric(5,4) NOT NULL,
            rule_satisfied   boolean NOT NULL,
            ai_verdict       text,
            ai_reason        text,
            ai_call_id       text,
            session_id       uuid REFERENCES play_sessions(id) ON DELETE SET NULL,
            created_at       timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ai_cannot_grant
                CHECK (to_state <> 'mastered' OR rule_satisfied = true)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS mastery_events_child_created "
        "ON mastery_events (child_id, created_at DESC)"
    )

    # --- the retrieval index ------------------------------------------------
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS child_memory (
            doc_id       text PRIMARY KEY,
            child_id     uuid NOT NULL REFERENCES children(id) ON DELETE CASCADE,
            kind         text NOT NULL,
            text_ar      text NOT NULL,
            occurred_at  timestamptz,
            metadata     jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            embedding    vector({EMBEDDING_DIM}) NOT NULL,
            embedder     text NOT NULL,
            updated_at   timestamptz NOT NULL DEFAULT now()
        )
    """)
    # Every search is scoped to one child, so the child filter has to be an
    # index seek rather than a filter applied after an ANN scan of everyone.
    op.execute(
        "CREATE INDEX IF NOT EXISTS child_memory_child ON child_memory (child_id, kind)"
    )
    # HNSW over cosine distance. The vectors are L2-normalised by the embedder,
    # so cosine and inner product rank identically; cosine is used because it is
    # the operator the query is written with and a mismatch between operator and
    # index is a silent sequential scan.
    op.execute(
        "CREATE INDEX IF NOT EXISTS child_memory_embedding_hnsw "
        "ON child_memory USING hnsw (embedding vector_cosine_ops)"
    )

    # --- the chat transcript ------------------------------------------------
    # `surface` separates the two audiences: a caregiver assistant and the
    # constrained child-facing one. They have different personas, different
    # guardrails and different retention, and one table with a discriminator is
    # what lets the erasure walk find both without knowing there are two.
    op.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id            uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            child_id      uuid NOT NULL REFERENCES children(id) ON DELETE CASCADE,
            caregiver_id  uuid REFERENCES caregivers(id) ON DELETE SET NULL,
            surface       text NOT NULL,
            role          text NOT NULL,
            text_ar       text NOT NULL,
            -- Which retrieved documents grounded an assistant turn. Kept so the
            -- clinician console can answer "why did it say that" without
            -- re-running retrieval against a corpus that has since changed.
            grounded_in   jsonb NOT NULL DEFAULT '[]'::jsonb,
            outcome       text NOT NULL DEFAULT 'ok',
            created_at    timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT chat_messages_surface CHECK (surface IN ('caregiver', 'child')),
            CONSTRAINT chat_messages_role CHECK (role IN ('user', 'assistant'))
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS chat_messages_child_created "
        "ON chat_messages (child_id, surface, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chat_messages")
    op.execute("DROP TABLE IF EXISTS child_memory")
    op.execute("DROP TABLE IF EXISTS mastery_events")
    op.execute("DROP TABLE IF EXISTS attempts")
    op.execute("DROP TABLE IF EXISTS play_sessions")
