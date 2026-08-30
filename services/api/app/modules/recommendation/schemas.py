"""Recommendation and retrieval schemas.

`source` is on the response on purpose. A caregiver never sees it, but the
clinician console does, and "was this the model or the engine" is the first
question anyone reviewing a bad recommendation will ask. Hiding it would make
the AI path and the fallback path indistinguishable from the outside, which is
the same as not being able to audit either.

No field here is a percentage, a percentile or a norm comparison, and
`p_known` never leaves the server on this route --
`test_no_dashboard_endpoint_exposes_a_norm` walks the whole OpenAPI document
for exactly that.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class NextExerciseResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: `<kind>:<skill code>`, the same activity-code shape `progress/history.py`
    #: produces, so the child app has one thing to resolve rather than two.
    activity_code: str
    skill_id: str
    skill_code: str
    label_ar: str
    #: lapsed | due | new | confidence — why the engine offered it at all.
    kind: str
    reason_ar: str
    source: Literal["ai", "deterministic_fallback"]
    #: The rest of the planned order, so the client can prefetch the session
    #: rather than asking again after every activity.
    plan: list[str] = Field(default_factory=list)
    #: Document ids the answer was grounded in. The audit trail, not a citation
    #: a caregiver reads.
    grounded_in: list[str] = Field(default_factory=list)


class ReindexResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indexed: int


class MemoryHit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str
    kind: str
    at: str
    score: float
    text_ar: str


class MemorySearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    hits: list[MemoryHit]


class MemorySearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: Annotated[str, Field(min_length=1, max_length=400)]
    k: Annotated[int, Field(ge=1, le=20)] = 8


__all__ = [
    "MemoryHit",
    "MemorySearchRequest",
    "MemorySearchResponse",
    "NextExerciseResponse",
    "ReindexResponse",
]
