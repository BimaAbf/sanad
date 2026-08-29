"""ORM models for children and consent. Mirrors docs/02-data-model.md §3."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM, INET, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

child_sex_enum = ENUM("male", "female", "unspecified", name="child_sex", create_type=False)
comms_level_enum = ENUM(
    "preverbal",
    "single_words",
    "two_word",
    "phrases",
    "sentences",
    name="comms_level",
    create_type=False,
)
consent_status_enum = ENUM("granted", "withdrawn", name="consent_status", create_type=False)
caregiver_role_enum = ENUM(
    "owner", "co_caregiver", "therapist", name="caregiver_role", create_type=False
)


class Child(Base):
    __tablename__ = "children"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v7()
    )
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    name_vowelised: Mapped[str | None] = mapped_column(Text)
    date_of_birth: Mapped[dt.date] = mapped_column(Date, nullable=False)
    sex: Mapped[str] = mapped_column(child_sex_enum, nullable=False, server_default="unspecified")
    gestational_weeks: Mapped[int | None] = mapped_column(SmallInteger)
    diagnosis_note: Mapped[str | None] = mapped_column(Text)
    comms_level: Mapped[str] = mapped_column(
        comms_level_enum, nullable=False, server_default="single_words"
    )
    wait_time_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default="8000")
    max_choices: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="2")
    audio_rate_pct: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="85")
    calm_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    session_minutes: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="8")
    hearing_aid: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    glasses: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    archived_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("wait_time_ms BETWEEN 3000 AND 20000", name="ck_children_wait_time"),
        CheckConstraint("max_choices BETWEEN 2 AND 4", name="ck_children_max_choices"),
        CheckConstraint("audio_rate_pct BETWEEN 60 AND 110", name="ck_children_audio_rate"),
        CheckConstraint("session_minutes BETWEEN 3 AND 15", name="ck_children_session_minutes"),
    )


class ConsentDefinition(Base):
    __tablename__ = "consent_definitions"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    text_ar: Mapped[str] = mapped_column(Text, nullable=False)
    text_en: Mapped[str] = mapped_column(Text, nullable=False)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False)
    effective_from: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Consent(Base):
    """Append-only. A withdrawal is a new row, never an UPDATE of the grant."""

    __tablename__ = "consents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v7()
    )
    child_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("children.id", ondelete="CASCADE"), nullable=False
    )
    caregiver_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("caregivers.id"), nullable=False
    )
    consent_key: Mapped[str] = mapped_column(
        Text, ForeignKey("consent_definitions.key"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(consent_status_enum, nullable=False)
    granted_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    withdrawn_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    source_ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_consents_child_key_granted", "child_id", "consent_key", granted_at.desc()),
    )


class CaregiverInvite(Base):
    __tablename__ = "caregiver_invites"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v7()
    )
    child_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("children.id", ondelete="CASCADE"), nullable=False
    )
    invited_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("caregivers.id", ondelete="CASCADE"), nullable=False
    )
    phone_e164: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(
        caregiver_role_enum, nullable=False, server_default="co_caregiver"
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("caregivers.id")
    )
    accepted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
