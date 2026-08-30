"""Play session schemas. docs/05 §6.

The manifest a session returns is everything the child app needs to run to the
end offline. That is not an optimisation: docs/04e §C13 says a network drop
after the first prompt must change nothing on screen, and a client that fetches
the next activity mid-session cannot honour that.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

#: attempt_result, from 0001. `incorrect` is recorded and never shown: there is
#: no failure state in the child UI, but the adaptive engine still needs to know.
AttemptResult = Literal[
    "correct", "incorrect", "no_response", "accepted_on_effort", "caregiver_confirmed"
]

#: prompt_level, from 0001. The rung of the prompt ladder the child was on.
PromptLevel = Literal["independent", "gestural", "partial_verbal", "full_model"]

Modality = Literal["receptive", "expressive", "productive"]

MAX_ATTEMPTS_PER_BATCH = 100


class SessionStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    child_id: UUID
    #: Overrides the child's configured `session_minutes` for this session only.
    minutes: Annotated[int | None, Field(ge=3, le=15)] = None


class ChoiceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: UUID
    code: str
    label_ar: str
    #: Never empty. A picture with no alt text is unusable with a screen reader
    #: and the seed guarantees the column is populated.
    alt_ar: str
    correct: bool


class ActivityOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: `<kind>:<skill code>` — the same shape `progress/history.py` produces.
    activity_code: str
    skill_id: UUID
    skill_code: str
    instruction_ar: str
    choices: list[ChoiceOut]


class SessionCreated(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    child_id: UUID
    started_at: dt.datetime
    #: 'ai' or 'deterministic_fallback'. Today always the latter, and named
    #: rather than hidden so the console can tell one from the other.
    plan_source: str
    #: Accessibility settings, sent with the plan so the child app never has to
    #: fetch the child record separately to know how long to wait.
    wait_time_ms: int
    max_choices: int
    calm_mode: bool
    activities: list[ActivityOut]


class AttemptIn(BaseModel):
    """One attempt as REPORTED by a caregiver. See `router.py`'s header.

    `result` is what the caller says happened. The child app does not use this
    model: it posts a response to the tutor loop and the server decides the
    result from the stored answer key.
    """

    model_config = ConfigDict(extra="forbid")

    activity_code: Annotated[str, Field(min_length=1, max_length=120)]
    skill_code: Annotated[str, Field(min_length=1, max_length=80)]
    result: AttemptResult
    prompt_level: PromptLevel = "independent"
    modality: Modality = "receptive"
    #: What the child actually tapped, when it was not the target. This is the
    #: whole reason attempts are stored per-attempt: a confusion pattern is not
    #: computable from a session total.
    selected_skill_code: str | None = None
    latency_ms: Annotated[int | None, Field(ge=0, le=600_000)] = None
    choice_count: Annotated[int, Field(ge=1, le=4)] = 2
    client_ts: dt.datetime | None = None
    #: Client-generated, stable across every retry of the same attempt. The
    #: outbox writes it before posting; the unique index is what makes a drain
    #: after a 30-second dropout create zero duplicates.
    idempotency_key: Annotated[str, Field(min_length=8, max_length=128)]


class AttemptBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempts: Annotated[list[AttemptIn], Field(min_length=1, max_length=MAX_ATTEMPTS_PER_BATCH)]


class AttemptAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: int
    duplicates: int


class SessionEnd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, Field(max_length=40)] = "completed"
    #: Wall-clock minutes the child was actually playing. The client knows this;
    #: the server would have to guess it from timestamps that include the time a
    #: tablet sat face-down on a table.
    minutes: Annotated[int, Field(ge=0, le=120)] = 0


class SessionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    ended_at: dt.datetime
    activities_done: int
    correct_count: int
