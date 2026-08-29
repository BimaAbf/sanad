"""Request/response schemas for the voice routes. docs/05 §6."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Verdict = Literal["accept", "retry", "unclear"]
Mode = Literal["asr", "caregiver_confirm", "say_together", "receptive_only"]


class AttemptResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Verdict
    similarity: Annotated[float, Field(ge=0.0, le=1.0)]
    #: Only the recognised word, never a free-form transcript (docs/04d §5).
    heard: str = ""
    feedback_audio_url: str = ""
    #: Tells the client to stop asking for audio for the rest of the session.
    mode: Mode = "asr"


class OverrideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    child_id: UUID
    activity_id: UUID
    skill_code: Annotated[str, Field(min_length=1, max_length=64)]


class OverrideResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recorded: bool = True


class TtsRequest(BaseModel):
    """Admin/preview only. The runtime plays manifest URLs, never this."""

    model_config = ConfigDict(extra="forbid")

    text: Annotated[str, Field(min_length=1, max_length=400)]
    voice: Annotated[str, Field(max_length=64)] = "nour"
    rate: Annotated[int, Field(ge=60, le=110)] = 85


class TtsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    cached: bool


class VoiceHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    providers: dict[str, str]
    cache_hit_rate: Annotated[float, Field(ge=0.0, le=1.0)]
    #: Non-empty means the rendered corpus has a gap and publish is blocked.
    missing_assets: int = 0
