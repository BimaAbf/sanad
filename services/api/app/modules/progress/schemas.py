"""Progress and event schemas. docs/05 §5.

No field on any response here is a percentile, a norm comparison or a DQ. That
is checked mechanically over the whole OpenAPI document by
`test_no_dashboard_endpoint_exposes_a_norm`, so it holds for endpoints nobody
has written yet.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

MAX_EVENTS_PER_BATCH = 200


class EventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=80)]
    props: dict[str, Any] = Field(default_factory=dict)
    client_ts: dt.datetime
    child_id: UUID | None = None
    #: Client-generated. Makes an outbox drain after a reconnect idempotent
    #: without the server having to guess what a duplicate looks like.
    idempotency_key: Annotated[str, Field(min_length=8, max_length=128)]


class EventBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: Annotated[list[EventIn], Field(min_length=1, max_length=MAX_EVENTS_PER_BATCH)]


class EventBatchAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: int
    duplicates: int


class ActivitySuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activity_code: str
    skill_id: str
    label_ar: str


class TodayResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str
    sessions: int
    minutes: int
    attempts: int
    streak_days: int
    suggestion: ActivitySuggestion | None = None
    #: Exactly 3 when present, never 1 or 2. See views.build_revisit_plan.
    revisit_plan: list[ActivitySuggestion] = Field(default_factory=list)
    regression_detected: bool = False


class SkillCardOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str
    code: str
    label_ar: str
    category: str
    state: str
    p_known: Annotated[float, Field(ge=0.0, le=1.0)]
    due_at: dt.datetime | None = None
    last_seen_at: dt.datetime | None = None


class SkillsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    mastered: int
    practising: int
    not_started: int
    by_category: dict[str, list[SkillCardOut]] = Field(default_factory=dict)


class JourneyPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessment_id: str
    completed_at: dt.date
    #: Developmental age in months per domain. Not a quotient, not a percentile.
    domain_da: dict[str, float]
    skills_mastered: int


class JourneyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "insufficient_data"]
    points: list[JourneyPoint] = Field(default_factory=list)
    #: Resolved by the client from the i18n bundle, so the copy stays inside the
    #: banned-terms lint.
    copy_key: str = ""
    revisit_plan: list[ActivitySuggestion] = Field(default_factory=list)


class AssessmentSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessment_id: str
    status: str
    started_at: dt.datetime
    completed_at: dt.datetime | None = None
    report_available: bool = False
