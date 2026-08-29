"""Enumerated types and required extensions.

Every ENUM in docs/02-data-model.md 2, created before any table so that later
migrations can reference them by name. Values are transcribed verbatim from the
data model; adding a value later is an additive migration, removing one is not
permitted (docs/08 4: migrations are forward-only and additive).

Revision ID: 0001_enum_types
Revises:
Create Date: 2026-08-29
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001_enum_types"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EXTENSIONS: tuple[str, ...] = ("pgcrypto", "vector")

ENUMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("caregiver_role", ("owner", "co_caregiver", "therapist")),
    ("child_sex", ("male", "female", "unspecified")),
    (
        "comms_level",
        ("preverbal", "single_words", "two_word", "phrases", "sentences"),
    ),
    ("consent_status", ("granted", "withdrawn")),
    (
        "assessment_status",
        ("draft", "in_progress", "paused", "scoring", "completed", "abandoned", "flagged"),
    ),
    ("response_verdict", ("yes", "emerging", "no", "not_applicable", "skipped")),
    (
        "response_source",
        (
            "caregiver_tap",
            "caregiver_text",
            "caregiver_voice",
            "clinician_override",
            "evidence_propagated",
        ),
    ),
    (
        "domain_code",
        ("infant_stim", "socialization", "language", "self_help", "cognitive", "motor"),
    ),
    (
        "skill_category",
        ("letters", "numbers", "colors", "body_parts", "household", "social"),
    ),
    (
        "activity_kind",
        ("listen_point", "match_pair", "say_it", "sort_category", "story_moment"),
    ),
    ("modality", ("receptive", "expressive", "productive")),
    (
        "mastery_state",
        ("not_started", "introduced", "practising", "mastered", "retained", "lapsed"),
    ),
    (
        "attempt_result",
        ("correct", "incorrect", "no_response", "accepted_on_effort", "caregiver_confirmed"),
    ),
    ("prompt_level", ("independent", "gestural", "partial_verbal", "full_model")),
    (
        "ai_decision_point",
        (
            "pgee_next_item",
            "pgee_interpret",
            "pgee_probe",
            "pgee_report",
            "tutor_plan",
            "tutor_judge",
            "tutor_summary",
            "safety_classify",
        ),
    ),
    (
        "guardrail_outcome",
        ("pass", "repaired", "rejected_fallback", "blocked_escalated"),
    ),
    (
        "escalation_category",
        (
            "seizure",
            "regression",
            "feeding_aspiration",
            "self_harm",
            "safeguarding",
            "medical_advice_requested",
            "distress",
            "other",
        ),
    ),
    ("escalation_status", ("open", "acknowledged", "resolved", "dismissed")),
    ("tts_voice", ("nour_child", "narrator_caregiver")),
)


def upgrade() -> None:
    for extension in EXTENSIONS:
        op.execute(f'CREATE EXTENSION IF NOT EXISTS "{extension}"')
    for name, values in ENUMS:
        rendered = ", ".join(f"'{value}'" for value in values)
        op.execute(f"CREATE TYPE {name} AS ENUM ({rendered})")


def downgrade() -> None:
    for name, _ in reversed(ENUMS):
        op.execute(f"DROP TYPE IF EXISTS {name}")
