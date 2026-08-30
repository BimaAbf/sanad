"""Assessment request/response models. docs/05 §4.

No response here carries a DQ, a percentile or an age comparison. `domain_da` is
a developmental age in months, which is the raw measure the report explains in
context -- the norm panel is opt-in and lives in the report, not on a dashboard.
`test_no_dashboard_endpoint_exposes_a_norm` checks that over the whole OpenAPI
document, so this stays true for fields nobody has added yet.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

#: The response_verdict enum from docs/02 §2, minus nothing. Spelled out as a
#: Literal rather than built from a tuple so the OpenAPI document names the five
#: values and a client can generate an exhaustive switch.
Verdict = Literal["yes", "emerging", "no", "not_applicable", "skipped"]

#: response_source, minus `evidence_propagated`: that one is written by the
#: engine, never sent by a client, and accepting it here would let a caller
#: forge inferred evidence as if the engine had derived it.
Source = Literal["caregiver_tap", "caregiver_text", "caregiver_voice", "clinician_override"]


class AssessmentStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    child_id: UUID


class ItemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    domain: str
    band: int
    ordinal: int
    #: Egyptian Arabic, which is what the caregiver reads by default.
    prompt_ar: str = ""
    #: MSA, shown on tap. Some caregivers read MSA more comfortably.
    prompt_ar_msa: str = ""
    #: docs/04e §C12: parents cannot answer abstract questions about their own
    #: child reliably. The concrete example is what makes the answer valid, so
    #: it is part of the item rather than a nicety.
    example_ar: str = ""


class AnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: Annotated[str, Field(min_length=1, max_length=120)]
    verdict: Verdict
    source: Source = "caregiver_tap"
    #: Client-generated. Makes the retry after a dropped connection a no-op
    #: rather than a second answer that moves the ceiling.
    idempotency_key: Annotated[str | None, Field(min_length=8, max_length=128)] = None


class AssessmentState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessment_id: UUID
    status: str
    bank_version: str
    #: Corrected age at administration. The report shows both; this is the one
    #: the entry bands used.
    child_months: float
    answered: int
    #: Only ever narrows. docs/04b: a progress range that grows is worse than
    #: none, because it reads as the end receding.
    remaining_estimate: int
    complete: bool
    next_items: list[ItemOut] = Field(default_factory=list)
    #: Non-empty while the item bank is unreviewed placeholder content. The
    #: runner renders it. A placeholder bank that looks like a real one is the
    #: failure this field exists to prevent.
    bank_watermark: str = ""


class AssessmentScored(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessment_id: UUID
    status: str
    completed_at: dt.datetime
    #: domain code -> developmental age in months.
    domain_da: dict[str, float]
    skills_mastered: int
