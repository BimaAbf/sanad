"""Request/response schemas for children and consent."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.children.domain import ConsentKey

Sex = Literal["male", "female", "unspecified"]
CommsLevel = Literal["preverbal", "single_words", "two_word", "phrases", "sentences"]
Role = Literal["owner", "co_caregiver", "therapist"]


class ConsentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: ConsentKey
    granted: bool


class AccessibilityProfile(BaseModel):
    """Bounds mirror the CHECK constraints in docs/02 §3.

    Validated here as well as in the database so a caregiver gets a readable
    Arabic message rather than a 500 from a constraint violation.
    """

    wait_time_ms: Annotated[int, Field(ge=3000, le=20000)] = 8000
    max_choices: Annotated[int, Field(ge=2, le=4)] = 2
    audio_rate_pct: Annotated[int, Field(ge=60, le=110)] = 85
    calm_mode: bool = False
    session_minutes: Annotated[int, Field(ge=3, le=15)] = 8
    hearing_aid: bool = False
    glasses: bool = False


class ChildCreate(AccessibilityProfile):
    model_config = ConfigDict(extra="forbid")

    display_name: Annotated[str, Field(min_length=1, max_length=80)]
    name_vowelised: Annotated[str, Field(max_length=120)] | None = None
    date_of_birth: dt.date
    sex: Sex = "unspecified"
    gestational_weeks: Annotated[int, Field(ge=22, le=45)] | None = None
    diagnosis_note: Annotated[str, Field(max_length=2000)] | None = None
    comms_level: CommsLevel = "single_words"
    consents: list[ConsentInput] = Field(default_factory=list)


class ChildPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: Annotated[str, Field(min_length=1, max_length=80)] | None = None
    name_vowelised: Annotated[str, Field(max_length=120)] | None = None
    diagnosis_note: Annotated[str, Field(max_length=2000)] | None = None
    comms_level: CommsLevel | None = None
    wait_time_ms: Annotated[int, Field(ge=3000, le=20000)] | None = None
    max_choices: Annotated[int, Field(ge=2, le=4)] | None = None
    audio_rate_pct: Annotated[int, Field(ge=60, le=110)] | None = None
    calm_mode: bool | None = None
    session_minutes: Annotated[int, Field(ge=3, le=15)] | None = None
    hearing_aid: bool | None = None
    glasses: bool | None = None


class ChildResponse(BaseModel):
    id: UUID
    display_name: str
    name_vowelised: str | None
    date_of_birth: dt.date
    sex: str
    gestational_weeks: int | None
    comms_level: str
    chronological_months: float
    corrected_months: float
    wait_time_ms: int
    max_choices: int
    audio_rate_pct: int
    calm_mode: bool
    session_minutes: int
    hearing_aid: bool
    glasses: bool
    version: int
    updated_at: dt.datetime


class ChildCreated(BaseModel):
    id: UUID
    chronological_months: float
    corrected_months: float
    next_action: str = "run_first_assessment"


class ConsentItem(BaseModel):
    key: str
    version: int
    status: str
    text_ar: str
    is_mandatory: bool
    granted_at: dt.datetime | None


class ConsentList(BaseModel):
    items: list[ConsentItem]


class ConsentChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: ConsentKey
    granted: bool


class InviteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone_e164: Annotated[str, Field(min_length=6, max_length=24)]
    role: Role = "co_caregiver"


class InviteCreated(BaseModel):
    invite_url: str
    expires_at: dt.datetime


class JobAccepted(BaseModel):
    job_id: UUID
