"""Chat request and response schemas.

`outcome` is on every response. A caregiver sees the text; the client uses the
outcome to decide how to render it -- an escalation is not styled like an
answer, and a blocked turn must not look like the assistant agreed with the
question. Collapsing all four outcomes into "here is some text" is how a refusal
gets read as advice.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.chat.domain import MAX_MESSAGE_CHARS

Outcome = Literal["ok", "escalated", "blocked", "fallback"]


class CaregiverAskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: Annotated[str, Field(min_length=1, max_length=MAX_MESSAGE_CHARS)]


class CaregiverAskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text_ar: str
    outcome: Outcome
    #: Document ids retrieved for this turn. The console's audit trail; the
    #: caregiver app does not render it.
    grounded_in: list[str] = Field(default_factory=list)


class ChildSayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: What the child said, already transcribed by the client. The server takes
    #: text, never audio, on this route -- see `speech.py` for why the chat path
    #: does not reuse the voice module's recogniser.
    heard: Annotated[str, Field(min_length=1, max_length=MAX_MESSAGE_CHARS)]


class ChildSayResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text_ar: str
    outcome: Outcome
    #: Which of the seven reviewed phrases was selected. Always one of them.
    phrase_id: str | None = None
    #: Key into the pre-rendered corpus, so the child app plays Nour's real
    #: voice rather than synthesising a new one.
    audio_key: str | None = None


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    text_ar: str
    at: str
    outcome: Outcome


class ChatHistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    surface: Literal["caregiver", "child"]
    messages: list[ChatMessageOut]


class SpeechCapabilityOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supported: bool
    provider: str
    #: What the client should do instead when `supported` is false.
    client_fallback: str
    detail_ar: str


class SpeechCapabilitiesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tts: SpeechCapabilityOut
    stt: SpeechCapabilityOut


__all__ = [
    "CaregiverAskRequest",
    "CaregiverAskResponse",
    "ChatHistoryResponse",
    "ChatMessageOut",
    "ChildSayRequest",
    "ChildSayResponse",
    "SpeechCapabilitiesResponse",
    "SpeechCapabilityOut",
]
