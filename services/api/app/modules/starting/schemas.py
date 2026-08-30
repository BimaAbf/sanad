"""Request and response models for the starting assessment.

`next_questions` only ever shrinks and `answered` only ever grows, which is
docs/04b's rule about progress: a bar that goes backwards reads as the end
receding, and a caregiver who has answered nine of thirteen questions about
their own child is not in a mood to be told there are now fifteen.

`watermark` is non-empty while the form is unreviewed placeholder content, and
the runner renders it. A placeholder instrument that looks exactly like a
reviewed one is the failure the field exists to prevent.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StartingStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    child_id: UUID


class OptionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label_ar: str


class QuestionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    #: One of the ten areas, or "" for a question about HOW to teach rather than
    #: about what the child knows.
    area: str
    prompt_ar: str
    #: The concrete situation that makes the answer reliable. docs/04e §C12.
    example_ar: str
    options: list[OptionOut]


class StartingState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessment_id: UUID
    child_id: UUID
    status: str
    form_version: str
    answered: int
    total: int
    complete: bool
    answers: dict[str, str] = Field(default_factory=dict)
    next_questions: list[QuestionOut] = Field(default_factory=list)
    watermark: str = ""


class AnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: Annotated[str, Field(min_length=1, max_length=64)]
    answer_id: Annotated[str, Field(min_length=1, max_length=64)]


class StartingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessment_id: UUID
    child_id: UUID
    status: str
    completed_at: dt.datetime
    #: area code -> band index 0..3, exactly as derived.
    area_levels: dict[str, int]
    supports: dict[str, Any]
    #: How many `skill_states` rows the finalisation created. Zero on a second
    #: finalise, and zero for a skill the child has already played — the seed
    #: never overwrites a state built from real attempts.
    skills_seeded: int
    #: Areas the form asked about that the curriculum has no skills for, named
    #: rather than silently dropped.
    unmapped_areas: list[str] = Field(default_factory=list)


class StartingSummary(BaseModel):
    """The caregiver's read of a child's starting point, for the profile page."""

    model_config = ConfigDict(extra="forbid")

    assessment_id: UUID
    child_id: UUID
    status: str
    completed_at: dt.datetime | None = None
    area_levels: dict[str, int] = Field(default_factory=dict)
    supports: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "AnswerIn",
    "OptionOut",
    "QuestionOut",
    "StartingResult",
    "StartingStart",
    "StartingState",
    "StartingSummary",
]
