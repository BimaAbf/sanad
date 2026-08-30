"""The tutor runtime: starting profile, delivered activities, rewards, summaries.

Everything the AI teaching loop needs that migration 0013 did not have. Six new
tables, three additive columns and one new `ai_decision_point` value. Nothing is
dropped or narrowed, so this does not need the `destructive-migration` label.

It deliberately does NOT touch `play_sessions.plan_source`, whose CHECK allows
('ai', 'deterministic_fallback'). The first draft widened it to admit a third
value naming the runtime loop. Widening a CHECK means dropping and re-adding it,
and `tools/guards/destructive_migration.py` failed the build on that — correctly
by its own rule, even though a weakened predicate is safe during a bake, because
the guard cannot tell a weakened one from a tightened one by reading it. The column was
not worth a schema change: `plan_source` describes how an UP-FRONT plan was
made, the loop makes no up-front plan, and the source of each decision is on its
own `ai_decisions` row, which is both finer-grained and already read by the
inspector. Sessions run by the loop write 'deterministic_fallback' — literally
true of the plan, which is empty — and are told apart from the manifest
planner's sessions by having `tutor_activities` rows at all.

Why each table exists, in the order the runtime touches them:

`starting_assessments`
    The caregiver questionnaire that gives a brand-new child a starting point.
    Answers are kept as the log they were entered as, and the derived levels
    are stored beside them rather than only applied — so "why did SANAD start
    my child here" is answerable months later, after the derivation has changed.

`learner_profiles`
    One row per child: the support and modality that work for them. Seeded from
    the starting assessment and then updated from what actually happens, which
    is the difference between an intake form and a learner model.

`tutor_activities`
    The activity as delivered, with the answer key in a column the client is
    never sent. This is the table that makes "the frontend does not decide
    educational correctness" enforceable rather than aspirational: the response
    endpoint evaluates against the row, and a client that posts a different
    answer key changes nothing. `UNIQUE (session_id, ordinal)` and the
    `pending` state make a re-requested activity the same activity.

`reward_events`
    Append-only, one row per rewarded event, `idempotency_key` UNIQUE. Stars are
    a SUM over this table and are never a counter that a retry can increment
    twice. Same reasoning as `attempts`.

`achievements`
    `UNIQUE (child_id, code)`, so an achievement is unlocked once for a child
    however many times the rule fires.

`session_summaries`
    The deterministic facts a session produced, and the narrative built FROM
    those facts. Stored separately (`facts` vs `narrative_ar`) so a narrative
    can be regenerated, or found to disagree with the facts, without the facts
    being lost.

Revision ID: 0014_tutor_runtime
Revises: 0013_ai_decisions_outcomes
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0014_tutor_runtime"
down_revision: str | None = "0013_ai_decisions_outcomes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The closed set of activity types the tutor may deliver. A CHECK rather than a
#: new enum type: `activity_kind` in 0001 is the five child-app screens and is
#: referenced by columns that must not change meaning, and adding values to it
#: would conflate two different vocabularies.
ACTIVITY_TYPES = (
    "select_picture",
    "count_objects",
    "match_pair",
    "listen_choose",
    "speak_word",
    "sort_category",
    "order_sequence",
    "trace_letter",
)


def upgrade() -> None:
    # `tutor_brain` is the decision point the runtime loop calls. Added the way
    # 0010_chat_decision_points added its two: ALTER TYPE ... ADD VALUE, which
    # is additive and cannot invalidate a stored row.
    op.execute("ALTER TYPE ai_decision_point ADD VALUE IF NOT EXISTS 'tutor_brain'")

    op.execute("""
        CREATE TABLE IF NOT EXISTS starting_assessments (
            id              uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            child_id        uuid NOT NULL REFERENCES children(id) ON DELETE CASCADE,
            started_by      uuid REFERENCES caregivers(id) ON DELETE SET NULL,
            status          text NOT NULL DEFAULT 'in_progress'
                            CHECK (status IN ('in_progress', 'completed')),
            form_version    text NOT NULL,
            -- question id -> answer id, as the caregiver entered it.
            answers         jsonb NOT NULL DEFAULT '{}'::jsonb,
            -- area code -> band (0..3), derived at finalisation.
            area_levels     jsonb NOT NULL DEFAULT '{}'::jsonb,
            -- The support observations: demonstration, spoken instructions,
            -- comfortable duration, selection support, speech comfort.
            supports        jsonb NOT NULL DEFAULT '{}'::jsonb,
            started_at      timestamptz NOT NULL DEFAULT now(),
            completed_at    timestamptz,
            updated_at      timestamptz NOT NULL DEFAULT now()
        )
    """)
    # One open assessment per child. A second one is a closed tab, not a second
    # administration, and the service resumes rather than forking the answers.
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS starting_assessments_one_open
        ON starting_assessments (child_id) WHERE status = 'in_progress'
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS learner_profiles (
            child_id                 uuid PRIMARY KEY
                                     REFERENCES children(id) ON DELETE CASCADE,
            source                   text NOT NULL DEFAULT 'starting_assessment',
            starting_assessment_id   uuid REFERENCES starting_assessments(id)
                                     ON DELETE SET NULL,
            effective_support        text NOT NULL DEFAULT 'medium'
                                     CHECK (effective_support IN ('low', 'medium', 'high')),
            effective_modality       text NOT NULL DEFAULT 'visual',
            demonstration_helps      boolean NOT NULL DEFAULT true,
            follows_spoken           boolean NOT NULL DEFAULT true,
            comfortable_speaking     boolean NOT NULL DEFAULT true,
            comfortable_minutes      smallint NOT NULL DEFAULT 8
                                     CHECK (comfortable_minutes BETWEEN 3 AND 20),
            area_levels              jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at               timestamptz NOT NULL DEFAULT now(),
            updated_at               timestamptz NOT NULL DEFAULT now()
        )
    """)

    checks = ", ".join(f"'{name}'" for name in ACTIVITY_TYPES)
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS tutor_activities (
            id              uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            session_id      uuid NOT NULL REFERENCES play_sessions(id) ON DELETE CASCADE,
            child_id        uuid NOT NULL REFERENCES children(id) ON DELETE CASCADE,
            decision_id     uuid REFERENCES ai_decisions(id) ON DELETE SET NULL,
            ordinal         smallint NOT NULL CHECK (ordinal >= 1),
            activity_type   text NOT NULL CHECK (activity_type IN ({checks})),
            skill_id        uuid NOT NULL REFERENCES skills(id),
            skill_code      text NOT NULL,
            difficulty      smallint NOT NULL CHECK (difficulty BETWEEN 1 AND 5),
            modality        modality NOT NULL,
            strategy        text NOT NULL,
            support_level   text NOT NULL CHECK (support_level IN ('low', 'medium', 'high')),
            prompt_level    prompt_level NOT NULL DEFAULT 'independent',
            choice_count    smallint NOT NULL DEFAULT 2 CHECK (choice_count >= 1),
            -- Exactly what the client is sent. Never contains the answer.
            presentation    jsonb NOT NULL,
            -- Server-only. The response endpoint evaluates against this.
            answer_key      jsonb NOT NULL,
            state           text NOT NULL DEFAULT 'pending'
                            CHECK (state IN ('pending', 'answered')),
            created_at      timestamptz NOT NULL DEFAULT now(),
            answered_at     timestamptz
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS tutor_activities_session_ordinal
        ON tutor_activities (session_id, ordinal)
    """)
    # At most one activity awaiting a response per session. Requesting the next
    # activity twice must return the same activity, not create a second one.
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS tutor_activities_one_pending
        ON tutor_activities (session_id) WHERE state = 'pending'
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS reward_events (
            id               uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            child_id         uuid NOT NULL REFERENCES children(id) ON DELETE CASCADE,
            session_id       uuid REFERENCES play_sessions(id) ON DELETE SET NULL,
            activity_id      uuid REFERENCES tutor_activities(id) ON DELETE SET NULL,
            kind             text NOT NULL
                             CHECK (kind IN ('activity', 'session_complete', 'achievement')),
            stars            smallint NOT NULL CHECK (stars >= 0),
            reason           text NOT NULL,
            idempotency_key  text NOT NULL,
            created_at       timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS reward_events_idempotency_key
        ON reward_events (idempotency_key)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS reward_events_child
        ON reward_events (child_id, created_at DESC)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS achievements (
            id           uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            child_id     uuid NOT NULL REFERENCES children(id) ON DELETE CASCADE,
            code         text NOT NULL,
            session_id   uuid REFERENCES play_sessions(id) ON DELETE SET NULL,
            awarded_at   timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS achievements_child_code
        ON achievements (child_id, code)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS session_summaries (
            session_id        uuid PRIMARY KEY REFERENCES play_sessions(id) ON DELETE CASCADE,
            child_id          uuid NOT NULL REFERENCES children(id) ON DELETE CASCADE,
            facts             jsonb NOT NULL,
            narrative_ar      text NOT NULL DEFAULT '',
            -- 'template' or 'ai'. Named rather than hidden, so the console can
            -- tell a generated summary from the fallback one.
            narrative_source  text NOT NULL DEFAULT 'template',
            created_at        timestamptz NOT NULL DEFAULT now()
        )
    """)

    # The BKT prior this child starts a skill from.
    #
    # `learning/service.py` recomputes `p_known` by folding the whole attempt
    # history from `BktState()` on every run, which is what makes the number
    # idempotent. That fold has to start SOMEWHERE, and starting every child at
    # the population default 0.15 throws away the one thing a caregiver
    # assessment produced: a different starting point per child per area. So
    # the prior is stored, seeded once when the starting assessment finalises,
    # and never written again — a constant of the fold rather than a running
    # value, which is exactly what keeps the fold idempotent.
    #
    # NULL means "no assessment for this skill", and the fold uses `bkt.P_L0`.
    op.execute("ALTER TABLE skill_states ADD COLUMN IF NOT EXISTS p_prior numeric(6,5)")

    # Drawing and speech metrics, on the row that already records an outcome.
    op.execute("ALTER TABLE activity_outcomes ADD COLUMN IF NOT EXISTS metrics jsonb")
    op.execute("ALTER TABLE activity_outcomes ADD COLUMN IF NOT EXISTS threshold numeric(5,4)")
    op.execute(
        "ALTER TABLE activity_outcomes ADD COLUMN IF NOT EXISTS activity_row_id uuid "
        "REFERENCES tutor_activities(id) ON DELETE CASCADE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE skill_states DROP COLUMN IF EXISTS p_prior")
    op.execute("ALTER TABLE activity_outcomes DROP COLUMN IF EXISTS activity_row_id")
    op.execute("ALTER TABLE activity_outcomes DROP COLUMN IF EXISTS threshold")
    op.execute("ALTER TABLE activity_outcomes DROP COLUMN IF EXISTS metrics")
    op.execute("DROP TABLE IF EXISTS session_summaries")
    op.execute("DROP TABLE IF EXISTS achievements")
    op.execute("DROP TABLE IF EXISTS reward_events")
    op.execute("DROP TABLE IF EXISTS tutor_activities")
    op.execute("DROP TABLE IF EXISTS learner_profiles")
    op.execute("DROP TABLE IF EXISTS starting_assessments")
    # `tutor_brain` stays in ai_decision_point: PostgreSQL cannot remove an enum
    # value, and a downgrade that recreated the type would have to rewrite every
    # column using it.
