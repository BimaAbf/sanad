"""Request/response schemas for identity."""

from __future__ import annotations

import re
from typing import Annotated
from uuid import UUID

import phonenumbers
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.identity.domain import OTP_DIGITS, PLAY_PIN_LENGTH

_OTP_RE = re.compile(rf"^\d{{{OTP_DIGITS}}}$")
_PIN_RE = re.compile(rf"^\d{{{PLAY_PIN_LENGTH}}}$")


def normalise_phone(raw: str) -> str:
    """Parse to E.164 or raise ValueError.

    Normalisation matters for correctness, not tidiness: `01001234567`,
    `+201001234567` and `0020 100 123 4567` are one person, and if they hash to
    three different rate-limit keys the 3-per-hour cap is trivially bypassed.
    Egypt (EG) is the default region because the product ships there first.
    """
    try:
        parsed = phonenumbers.parse(raw, "EG")
    except phonenumbers.NumberParseException as exc:
        raise ValueError("not a valid phone number") from exc
    if not phonenumbers.is_valid_number(parsed):
        raise ValueError("not a valid phone number")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


class OtpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone_e164: Annotated[str, Field(min_length=6, max_length=24)]

    @field_validator("phone_e164")
    @classmethod
    def _normalise(cls, value: str) -> str:
        return normalise_phone(value)


class OtpVerify(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone_e164: Annotated[str, Field(min_length=6, max_length=24)]
    code: Annotated[str, Field(min_length=OTP_DIGITS, max_length=OTP_DIGITS)]

    @field_validator("phone_e164")
    @classmethod
    def _normalise(cls, value: str) -> str:
        return normalise_phone(value)

    @field_validator("code")
    @classmethod
    def _digits(cls, value: str) -> str:
        if not _OTP_RE.match(value):
            raise ValueError(f"code must be {OTP_DIGITS} digits")
        return value


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"  # noqa: S105 -- a scheme name, not a credential
    expires_in: int
    is_new_user: bool = False


class CaregiverChildLink(BaseModel):
    id: UUID
    display_name: str
    role: str


class MeResponse(BaseModel):
    id: UUID
    display_name: str
    phone_e164: str | None
    email: str | None
    relationship: str | None
    governorate: str | None
    locale: str
    has_play_pin: bool
    children: list[CaregiverChildLink]


class MePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: Annotated[str, Field(max_length=120)] | None = None
    relationship: Annotated[str, Field(max_length=60)] | None = None
    governorate: Annotated[str, Field(max_length=60)] | None = None
    locale: Annotated[str, Field(max_length=12)] | None = None


class PlayPinSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pin: Annotated[str, Field(min_length=PLAY_PIN_LENGTH, max_length=PLAY_PIN_LENGTH)]

    @field_validator("pin")
    @classmethod
    def _digits(cls, value: str) -> str:
        if not _PIN_RE.match(value):
            raise ValueError(f"pin must be {PLAY_PIN_LENGTH} digits")
        return value


class PlayPinVerifyResponse(BaseModel):
    ok: bool
