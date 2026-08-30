"""Request and response models for the tutor loop.

**There is no field on any response here that carries the answer.** The
`presentation` a client receives is the stored JSON minus nothing, because the
stored JSON never had the answer in it — the answer key is a separate column
and `ActivityOut` has no place to put it. That is the wire-format half of "the
frontend does not decide correctness"; `service.respond` is the other half.

`ResponseIn.response` is a free-form object rather than a discriminated union
because the eight activity types take six shapes and the evaluator already
refuses the wrong one by name (`ResponseInvalid` -> 422 with the reason). A
pydantic union would move that error earlier and make it less legible, and the
authoritative check would still have to exist.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Outcome = Literal["correct", "incorrect", "uncertain", "no_response"]
NextAction = Literal["next", "retry", "support"]
SupportAction = Literal["none", "demonstrate", "caregiver_confirm", "simplify"]
PromptLevel = Literal["independent", "gestural", "partial_verbal", "full_model"]


class SessionStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    child_id: UUID


class SessionCreated(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    child_id: UUID
    started_at: dt.datetime
    #: Accessibility settings, sent once so the child app never has to fetch the
    #: child record separately to know how long to wait.
    wait_time_ms: int
    max_choices: int
    audio_rate_pct: int
    calm_mode: bool


class ActivityOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: True when there is nothing more to deliver. Every other field is empty.
    #: An explicit state rather than a 404, because "the session is over" is a
    #: success and the client renders a closing scene for it.
    session_finished: bool = False
    activity_id: UUID | None = None
    ordinal: int = 0
    activity_type: str = ""
    skill_code: str = ""
    difficulty: int = 0
    modality: str = ""
    strategy: str = ""
    support_level: str = ""
    choice_count: int = 0
    #: The document the child's device renders. Never contains the answer.
    presentation: dict[str, Any] = Field(default_factory=dict)
    wait_time_ms: int = 8000
    #: 'groq:live', 'anthropic:live' or 'deterministic_fallback'. Named rather
    #: than hidden so a demo can tell a real model call from the fallback.
    decision_source: str = ""
    #: Present on a freshly decided activity, empty on a re-delivered one.
    reason_codes: list[str] = Field(default_factory=list)
    guardrail_actions: list[str] = Field(default_factory=list)


class ResponseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activity_id: UUID
    #: What the child did. Shape depends on the activity type; the evaluator
    #: refuses a mismatch with a 422 naming both.
    response: dict[str, Any]
    #: Client-generated and stable across every retry of the same response.
    #: The unique index on `attempts.idempotency_key` is what makes a double
    #: tap one attempt and one star.
    idempotency_key: Annotated[str, Field(min_length=8, max_length=128)]
    latency_ms: Annotated[int | None, Field(ge=0, le=600_000)] = None
    #: Which rung of the prompt ladder the child answered at. The server raises
    #: it when the activity itself carried a demonstration — a client cannot
    #: report independence for an activity it was told to demonstrate first.
    prompt_level: PromptLevel = "independent"


class ResponseOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activity_id: UUID
    #: The authoritative verdict. The client renders this; it does not compute
    #: its own and it never celebrates when this is false.
    correct: bool
    outcome: Outcome
    next_action: NextAction
    support_action: SupportAction
    #: Stars this response added. Zero on a duplicate, which is what makes rapid
    #: tapping cost nothing.
    reward_delta: int
    #: Read back from the database after the write, never computed forward.
    stars_total: int
    achievements_unlocked: list[str] = Field(default_factory=list)
    #: True when the idempotency key was already on file. The response is
    #: otherwise identical, so a retry is safe and visibly a retry.
    duplicate: bool = False
    #: Drawing and speech carry a score against a threshold; everything else
    #: leaves them null rather than inventing a number.
    score: float | None = None
    threshold: float | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
    mastery_before: float | None = None
    mastery_after: float | None = None
    mastery_state: str = ""


class SessionEnd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, Field(max_length=40)] = "completed"
    minutes: Annotated[int, Field(ge=0, le=120)] = 0


class SessionResult(BaseModel):
    """What the child's closing scene and the caregiver report both read.

    The child app uses `stars_earned`, `achievements_unlocked` and
    `skills_practised_ar`. It never renders `correct`, `incorrect` or any ratio
    — docs/04e §C13 has no failure state, and "4 out of 7" is one.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    ended_at: dt.datetime
    activities_completed: int
    correct: int
    incorrect: int
    no_response: int
    independent_responses: int
    supported_responses: int
    skills_practised: list[str]
    skills_practised_ar: list[str]
    activity_types: list[str]
    mastery_changes: list[dict[str, str]]
    stars_earned: int
    stars_total: int
    achievements_unlocked: list[str]
    duration_minutes: int
    best_streak: int
    went_well_ar: list[str]
    needs_practice_ar: list[str]
    narrative_ar: str
    #: 'template' or 'ai'.
    narrative_source: str


class CaregiverReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    child_id: UUID
    created_at: dt.datetime
    facts: dict[str, Any]
    narrative_ar: str
    narrative_source: str


class SessionHistoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    started_at: dt.datetime
    ended_at: dt.datetime | None = None
    activities_done: int
    correct_count: int
    stars: int
    #: Null for a session that ended without producing a summary — an abandoned
    #: session is still a session, and hiding it would make a caregiver's
    #: history quietly shorter than their child's.
    facts: dict[str, Any] | None = None
    narrative_ar: str = ""
    narrative_source: str = ""


class SessionHistory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    child_id: UUID
    sessions: list[SessionHistoryItem]


class AchievementOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    label_ar: str
    awarded_at: dt.datetime


class RewardsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    child_id: UUID
    stars: int
    achievements: list[AchievementOut]


class InspectorDecision(BaseModel):
    """One teaching decision, exactly as it was recorded.

    Every field is nullable and the panel renders "غير متاح" for a null. A
    decision taken before a field existed has no value for it, and inventing
    one would make the inspector the least trustworthy screen in the product.
    """

    model_config = ConfigDict(extra="forbid")

    decision_id: str
    ordinal: int
    created_at: dt.datetime
    model_name: str
    used_ai: bool
    skill: str | None = None
    difficulty: int | None = None
    strategy: str | None = None
    modality: str | None = None
    support_level: str | None = None
    activity_type: str | None = None
    repeat: bool | None = None
    reason_codes: list[str] = Field(default_factory=list)
    guardrail_actions: list[str] = Field(default_factory=list)
    changed_by_guardrails: bool = False
    p_known_at_decision: float | None = None
    recent_results: list[str] = Field(default_factory=list)
    modality_accuracy: dict[str, float] = Field(default_factory=dict)
    resulting_activity: str | None = None


class InspectorActivity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ordinal: int
    activity_type: str
    skill_code: str
    skill_label_ar: str
    difficulty: int
    strategy: str
    support_level: str
    state: str


class InspectorAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_code: str
    result: str
    prompt_level: str
    latency_ms: int | None = None


class InspectorOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    child_id: UUID
    plan_source: str
    decisions: list[InspectorDecision]
    activities: list[InspectorActivity]
    attempts: list[InspectorAttempt]


__all__ = [
    "AchievementOut",
    "ActivityOut",
    "CaregiverReport",
    "InspectorActivity",
    "InspectorAttempt",
    "InspectorDecision",
    "InspectorOut",
    "ResponseIn",
    "ResponseOut",
    "RewardsOut",
    "SessionCreated",
    "SessionEnd",
    "SessionHistory",
    "SessionHistoryItem",
    "SessionResult",
    "SessionStart",
]
