"""Auditable tutor decisions and reconstructable activity outcomes.

Only concise reason codes and structured decisions are stored; hidden model
reasoning is intentionally never persisted. Child-owned rows cascade on erasure.

Revision ID: 0013_ai_decisions_outcomes
Revises: 0012_skill_states_modality_key
"""
from __future__ import annotations

from collections.abc import Sequence
from alembic import op

revision: str = "0013_ai_decisions_outcomes"
down_revision: str | None = "0012_skill_states_modality_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS ai_decisions (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            child_id uuid NOT NULL REFERENCES children(id) ON DELETE CASCADE,
            session_id uuid REFERENCES play_sessions(id) ON DELETE SET NULL,
            state_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
            proposed_decision jsonb NOT NULL,
            final_decision jsonb NOT NULL,
            reason_codes jsonb NOT NULL DEFAULT '[]'::jsonb,
            guardrail_actions jsonb NOT NULL DEFAULT '[]'::jsonb,
            model_name text NOT NULL DEFAULT 'deterministic_fallback',
            outcome_summary text,
            resulting_activity_id text,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ai_decisions_child_created ON ai_decisions (child_id, created_at DESC)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS activity_outcomes (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            child_id uuid NOT NULL REFERENCES children(id) ON DELETE CASCADE,
            session_id uuid NOT NULL REFERENCES play_sessions(id) ON DELETE CASCADE,
            activity_id text NOT NULL,
            skill_id uuid NOT NULL REFERENCES skills(id),
            difficulty smallint NOT NULL CHECK (difficulty BETWEEN 1 AND 5),
            modality text NOT NULL,
            teaching_strategy text NOT NULL,
            character text NOT NULL CHECK (character IN ('mano', 'kira')),
            expected_answer text,
            learner_response text,
            asr_transcript text,
            asr_confidence numeric(5,4),
            correctness boolean,
            similarity numeric(5,4),
            pronunciation_score numeric(5,4),
            response_time_ms integer CHECK (response_time_ms >= 0),
            retries smallint NOT NULL DEFAULT 0 CHECK (retries >= 0),
            hints smallint NOT NULL DEFAULT 0 CHECK (hints >= 0),
            prompt_level prompt_level NOT NULL DEFAULT 'independent',
            completed boolean NOT NULL DEFAULT true,
            mastery_before numeric(5,4),
            mastery_after numeric(5,4),
            ai_decision_id uuid REFERENCES ai_decisions(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS activity_outcomes_child_created ON activity_outcomes (child_id, created_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS activity_outcomes")
    op.execute("DROP TABLE IF EXISTS ai_decisions")
