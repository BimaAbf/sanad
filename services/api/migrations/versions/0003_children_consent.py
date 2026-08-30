"""Children, consent definitions and the consent ledger.

DDL transcribed from docs/02-data-model.md §3. The seven consent keys are seeded
here rather than in seeds/ because the *wording* is legally significant: it is
versioned, auditable, and a caregiver consented to a specific text. Changing a
text_ar requires a new version row, never an UPDATE.

Revision ID: 0003_children_consent
Revises: 0002_identity
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_children_consent"
down_revision: str | None = "0002_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (key, text_ar, text_en, is_mandatory)
#
# PLACEHOLDER — NOT FOR CLINICAL USE.
# The Arabic wording below is agent-drafted scaffolding so the flow is testable.
# Consent text is a legal instrument under Egypt PDPL 151/2020: it must be
# written by a lawyer and reviewed by a native Egyptian Arabic speaker before any
# real family sees it. Tracked in REVIEW-QUEUE.md.
CONSENTS: tuple[tuple[str, str, str, bool], ...] = (
    (
        "data_processing",
        "أوافق إن سند يحفظ بيانات طفلي وتقدّمه.",
        "I agree that Sanad may store my child's profile and progress.",
        True,
    ),
    (
        "ai_processing",
        "أوافق إن سند يبعت نصوص من غير أسماء لمساعد ذكي عشان يساعد في التقييم.",
        "I agree that Sanad may send pseudonymised text to an AI assistant to support assessment.",
        True,
    ),
    (
        "terms_not_medical",
        "فاهم إن سند مش خدمة طبية ولا بيشخّص.",
        "I understand that Sanad is not a diagnostic or medical service.",
        True,
    ),
    (
        "voice_asr",
        "أوافق إن سند يحوّل كلام طفلي لنص عشان يتأكد من النطق. الصوت مش بيتخزن.",
        "I agree that Sanad may transcribe my child's speech. The audio is not retained.",
        False,
    ),
    (
        "voice_retention",
        "أوافق إن سند يحتفظ بصوت طفلي ٣٠ يوم عشان يتحسّن التعرّف على كلامه.",
        "I agree that Sanad may keep 30 days of audio to improve recognition for this child.",
        False,
    ),
    (
        "clinician_share",
        "أوافق إن سند يشارك تقارير طفلي مع الأخصائي المرتبط بحسابي.",
        "I agree that Sanad may share my child's reports with a linked clinician.",
        False,
    ),
    (
        "research_aggregate",
        "أوافق باستخدام بيانات مجمّعة ومن غير أي أسماء في البحث العلمي.",
        "I agree to the use of fully anonymised, aggregated data for research.",
        False,
    ),
)


def upgrade() -> None:
    op.execute("""
        CREATE TABLE children (
            id                    uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            display_name          text NOT NULL,
            name_vowelised        text,
            date_of_birth         date NOT NULL,
            sex                   child_sex NOT NULL DEFAULT 'unspecified',
            gestational_weeks     smallint,
            diagnosis_note        text,
            comms_level           comms_level NOT NULL DEFAULT 'single_words',
            wait_time_ms          integer  NOT NULL DEFAULT 8000
                                  CHECK (wait_time_ms BETWEEN 3000 AND 20000),
            max_choices           smallint NOT NULL DEFAULT 2
                                  CHECK (max_choices BETWEEN 2 AND 4),
            audio_rate_pct        smallint NOT NULL DEFAULT 85
                                  CHECK (audio_rate_pct BETWEEN 60 AND 110),
            calm_mode             boolean  NOT NULL DEFAULT false,
            session_minutes       smallint NOT NULL DEFAULT 8
                                  CHECK (session_minutes BETWEEN 3 AND 15),
            hearing_aid           boolean  NOT NULL DEFAULT false,
            glasses               boolean  NOT NULL DEFAULT false,
            archived_at           timestamptz,
            created_at            timestamptz NOT NULL DEFAULT now(),
            updated_at            timestamptz NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE consent_definitions (
            key            text PRIMARY KEY,
            version        integer NOT NULL,
            text_ar        text NOT NULL,
            text_en        text NOT NULL,
            is_mandatory   boolean NOT NULL,
            effective_from timestamptz NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE consents (
            id             uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            child_id       uuid NOT NULL REFERENCES children(id) ON DELETE CASCADE,
            caregiver_id   uuid NOT NULL REFERENCES caregivers(id),
            consent_key    text NOT NULL REFERENCES consent_definitions(key),
            version        integer NOT NULL,
            status         consent_status NOT NULL,
            granted_at     timestamptz NOT NULL DEFAULT now(),
            withdrawn_at   timestamptz,
            source_ip      inet,
            user_agent     text
        )
    """)
    op.execute(
        "CREATE INDEX ix_consents_child_key_granted "
        "ON consents (child_id, consent_key, granted_at DESC)"
    )

    # Co-caregiver invites. Not in docs/02 §3 — the DDL there has caregiver_child
    # but nowhere to hold a pending invitation, and docs/04a §C02 requires a
    # signed, single-use, 7-day token. Recorded in docs/adr/003-consent-model.md.
    op.execute("""
        CREATE TABLE caregiver_invites (
            id            uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            child_id      uuid NOT NULL REFERENCES children(id) ON DELETE CASCADE,
            invited_by    uuid NOT NULL REFERENCES caregivers(id) ON DELETE CASCADE,
            phone_e164    text NOT NULL,
            role          caregiver_role NOT NULL DEFAULT 'co_caregiver',
            token_hash    text NOT NULL UNIQUE,
            accepted_by   uuid REFERENCES caregivers(id),
            accepted_at   timestamptz,
            revoked_at    timestamptz,
            expires_at    timestamptz NOT NULL,
            created_at    timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_caregiver_invites_child ON caregiver_invites (child_id)")

    # Bound parameters, not string interpolation: the Arabic text contains
    # apostrophes and is legally significant, so it must land in the row byte
    # for byte.
    insert = sa.text(
        "INSERT INTO consent_definitions (key, version, text_ar, text_en, is_mandatory) "
        "VALUES (:key, :version, :text_ar, :text_en, :is_mandatory)"
    )
    connection = op.get_bind()
    for key, text_ar, text_en, mandatory in CONSENTS:
        connection.execute(
            insert,
            {
                "key": key,
                "version": 1,
                "text_ar": text_ar,
                "text_en": text_en,
                "is_mandatory": mandatory,
            },
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS caregiver_invites")
    op.execute("DROP TABLE IF EXISTS consents")
    op.execute("DROP TABLE IF EXISTS consent_definitions")
    op.execute("DROP TABLE IF EXISTS children")
