"""Turning a child's database history into retrievable documents.

The retrieval corpus is **built, not stored raw**. Rows in `attempts` and
`skill_states` are numbers; what gets embedded and later handed to a model is a
short Arabic sentence that says what those numbers mean. Two reasons, and the
second is the important one:

1. The embedder indexes text, and a row of floats has no lexical content to
   index. A sentence naming the skill and its category does.
2. **This is the redaction boundary for retrieval.** Everything the retriever
   can ever return is constructed here, from an explicit list of fields. A
   `SELECT *` fed into an index is a design where the next column somebody adds
   to `children` -- a diagnosis note, a clinician's free text -- silently
   becomes retrievable and ends up in a prompt. Nothing here reads a field it
   was not written to read, and `FORBIDDEN_DOCUMENT_FIELDS` is asserted over the
   built corpus by a test rather than trusted as a convention.

What is deliberately excluded, and why -- this is the same list as
`tutor_ai/evidence.py` and for the same reason:

  * the child's name, date of birth, age in years, diagnosis note. The judge
    must not know the child has Down syndrome; expectation effects are real in
    models as in people, and a retrieved document saying so would reintroduce
    through the back door exactly what the evidence bundle excludes at the
    front.
  * anything a caregiver typed. Free text is screened as *input* by
    `guardrails.layers.screen_input` on the way in; indexing it would make it
    retrievable later, past the screen.

Pure. No I/O. Every function takes facts and returns documents.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

#: Keys that must never appear in a document's text or metadata. Walked by a
#: test over the whole built corpus, not merely respected by convention.
FORBIDDEN_DOCUMENT_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "display_name",
        "child_name",
        "name_vowelised",
        "age",
        "age_years",
        "date_of_birth",
        "dob",
        "diagnosis",
        "diagnosis_note",
        "phone",
        "phone_e164",
        "caregiver_id",
    }
)

#: Arabic labels for the mastery states. The caregiver-facing chat reads these
#: back verbatim, so they are the product's words rather than the database's.
STATE_AR: dict[str, str] = {
    "not_started": "لسه مبدأش",
    "introduced": "اتعرّف عليها",
    "practising": "بيتدرب عليها",
    "mastered": "أتقنها",
    "retained": "محتفظ بيها",
    "lapsed": "محتاجة مراجعة",
}

CATEGORY_AR: dict[str, str] = {
    "letters": "حروف",
    "numbers": "أرقام",
    "colors": "ألوان",
    "body_parts": "أجزاء الجسم",
    "household": "أدوات البيت",
    "social": "تواصل اجتماعي",
}

COMMS_AR: dict[str, str] = {
    "preverbal": "لسه مش بيتكلم",
    "single_words": "كلمة واحدة",
    "two_word": "كلمتين مع بعض",
    "phrases": "جمل قصيرة",
    "sentences": "جمل كاملة",
}


class DocumentKind(StrEnum):
    PROFILE = "profile"
    SKILL = "skill"
    SESSION = "session"
    CONFUSION = "confusion"
    MILESTONE = "milestone"


@dataclass(frozen=True, slots=True)
class MemoryDocument:
    """One retrievable unit.

    `doc_id` is deterministic and stable across rebuilds -- it is the upsert key,
    so re-indexing a child updates rows in place instead of accumulating a new
    copy of their history every night.
    """

    doc_id: str
    kind: DocumentKind
    text_ar: str
    occurred_at: dt.datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_langchain(self) -> dict[str, Any]:
        """The shape `retriever.py` hands to LangChain."""
        return {
            "page_content": self.text_ar,
            "metadata": {
                "doc_id": self.doc_id,
                "kind": self.kind.value,
                "at": self.occurred_at.date().isoformat() if self.occurred_at else "",
                **self.metadata,
            },
        }


# --- the facts the repository supplies --------------------------------------


@dataclass(frozen=True, slots=True)
class ProfileFact:
    """The functional half of `children`. No identity, by construction."""

    comms_level: str
    wait_time_ms: int
    max_choices: int
    audio_rate_pct: int
    calm_mode: bool
    session_minutes: int
    hearing_aid: bool
    glasses: bool


@dataclass(frozen=True, slots=True)
class SkillFact:
    skill_id: str
    code: str
    label_ar: str
    category: str
    state: str
    p_known: float
    due_at: dt.datetime | None
    updated_at: dt.datetime | None
    total_attempts: int = 0
    total_correct: int = 0
    independent_attempts: int = 0


@dataclass(frozen=True, slots=True)
class SessionFactRow:
    session_id: str
    started_at: dt.datetime
    minutes: int
    attempts: int
    correct: int
    ended_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ConfusionFact:
    """A wrong choice this child makes repeatedly.

    A single wrong tap is a random tap. The same wrong tap four times is the
    child telling you something about how they have carved up the category, and
    it is the single most actionable thing in this corpus.
    """

    skill_code: str
    label_ar: str
    confused_with_code: str
    confused_with_label_ar: str
    occurrences: int
    last_at: dt.datetime | None = None


@dataclass(frozen=True, slots=True)
class MilestoneFact:
    skill_code: str
    label_ar: str
    from_state: str
    to_state: str
    at: dt.datetime


# --- builders ---------------------------------------------------------------


def _pct(numerator: int, denominator: int) -> int:
    return round(100 * numerator / denominator) if denominator else 0


def profile_document(child_id: str, fact: ProfileFact) -> MemoryDocument:
    """How this child plays. Retrieved for almost every question.

    Note what makes this useful and safe at once: `max_choices` and
    `wait_time_ms` are exactly what a recommendation has to respect, and neither
    of them says anything about who the child is.
    """
    parts = [
        f"مستوى التواصل: {COMMS_AR.get(fact.comms_level, fact.comms_level)}.",
        f"عدد الاختيارات في النشاط: {fact.max_choices}.",
        f"وقت الانتظار قبل المساعدة: {fact.wait_time_ms // 1000} ثانية.",
        f"طول الجلسة المفضّل: {fact.session_minutes} دقيقة.",
        f"سرعة الصوت: {fact.audio_rate_pct}%.",
    ]
    if fact.calm_mode:
        parts.append("وضع الهدوء مفعّل.")
    if fact.hearing_aid:
        parts.append("بيستخدم سماعة أذن.")
    if fact.glasses:
        parts.append("بيلبس نضارة.")
    return MemoryDocument(
        doc_id=f"{child_id}:profile",
        kind=DocumentKind.PROFILE,
        text_ar=" ".join(parts),
        metadata={
            "max_choices": fact.max_choices,
            "wait_time_ms": fact.wait_time_ms,
            "calm_mode": fact.calm_mode,
            "session_minutes": fact.session_minutes,
        },
    )


def skill_document(child_id: str, fact: SkillFact) -> MemoryDocument:
    """One skill, in words.

    `p_known` is in the metadata and NOT in the text. docs/04a forbids showing a
    caregiver a mastery percentage, and the text of this document is what a
    caregiver-facing model gets to read back. The number stays available to the
    judge, which reads metadata.
    """
    state_ar = STATE_AR.get(fact.state, fact.state)
    category_ar = CATEGORY_AR.get(fact.category, fact.category)
    parts = [f"مهارة «{fact.label_ar}» ({category_ar}): {state_ar}."]
    if fact.total_attempts:
        parts.append(
            f"جرّبها {fact.total_attempts} مرة، صح في "
            f"{_pct(fact.total_correct, fact.total_attempts)}% منهم."
        )
        parts.append(
            f"من غير مساعدة في {_pct(fact.independent_attempts, fact.total_attempts)}% "
            "من المحاولات."
        )
    if fact.state == "lapsed":
        parts.append("محتاجة رجوع ليها قريب.")
    return MemoryDocument(
        doc_id=f"{child_id}:skill:{fact.code}",
        kind=DocumentKind.SKILL,
        text_ar=" ".join(parts),
        occurred_at=fact.updated_at,
        metadata={
            "skill_id": fact.skill_id,
            "skill_code": fact.code,
            "category": fact.category,
            "state": fact.state,
            "p_known": round(fact.p_known, 4),
            "due_at": fact.due_at.isoformat() if fact.due_at else "",
            "attempts": fact.total_attempts,
        },
    )


def session_document(child_id: str, fact: SessionFactRow) -> MemoryDocument:
    accuracy = _pct(fact.correct, fact.attempts)
    parts = [
        f"جلسة يوم {fact.started_at.date().isoformat()}:",
        f"{fact.minutes} دقيقة، {fact.attempts} محاولة، صح في {accuracy}% منهم.",
    ]
    if fact.ended_reason == "fatigue":
        parts.append("الجلسة قفلت بدري لأنه تعب.")
    elif fact.ended_reason == "caregiver_ended":
        parts.append("الجلسة اتقفلت من المسؤول.")
    return MemoryDocument(
        doc_id=f"{child_id}:session:{fact.session_id}",
        kind=DocumentKind.SESSION,
        text_ar=" ".join(parts),
        occurred_at=fact.started_at,
        metadata={
            "session_id": fact.session_id,
            "minutes": fact.minutes,
            "attempts": fact.attempts,
            "accuracy_pct": accuracy,
            "ended_reason": fact.ended_reason or "",
        },
    )


def confusion_document(child_id: str, fact: ConfusionFact) -> MemoryDocument:
    return MemoryDocument(
        doc_id=f"{child_id}:confusion:{fact.skill_code}:{fact.confused_with_code}",
        kind=DocumentKind.CONFUSION,
        text_ar=(
            f"لما بنسأل عن «{fact.label_ar}» بيختار «{fact.confused_with_label_ar}» "
            f"بدالها — حصلت {fact.occurrences} مرات."
        ),
        occurred_at=fact.last_at,
        metadata={
            "skill_code": fact.skill_code,
            "confused_with": fact.confused_with_code,
            "occurrences": fact.occurrences,
        },
    )


def milestone_document(child_id: str, fact: MilestoneFact) -> MemoryDocument:
    return MemoryDocument(
        doc_id=f"{child_id}:milestone:{fact.skill_code}:{fact.at.isoformat()}",
        kind=DocumentKind.MILESTONE,
        text_ar=(
            f"يوم {fact.at.date().isoformat()} مهارة «{fact.label_ar}» بقت "
            f"{STATE_AR.get(fact.to_state, fact.to_state)}."
        ),
        occurred_at=fact.at,
        metadata={
            "skill_code": fact.skill_code,
            "from_state": fact.from_state,
            "to_state": fact.to_state,
        },
    )


#: A confusion below this many occurrences is noise, not a pattern. Three is the
#: smallest count at which the same wrong choice is more likely than chance for
#: a two-choice activity over a handful of attempts.
MIN_CONFUSION_OCCURRENCES = 3


def build_corpus(
    child_id: str,
    *,
    profile: ProfileFact | None = None,
    skills: Sequence[SkillFact] = (),
    sessions: Sequence[SessionFactRow] = (),
    confusions: Sequence[ConfusionFact] = (),
    milestones: Sequence[MilestoneFact] = (),
) -> list[MemoryDocument]:
    """Every document for one child, in a stable order.

    Skills that have never been touched are skipped. Indexing 88 identical
    "has not started" sentences would make them the majority of the corpus and
    they would crowd out the documents that say something -- the retrieval
    equivalent of a page of blank rows.
    """
    documents: list[MemoryDocument] = []
    if profile is not None:
        documents.append(profile_document(child_id, profile))
    documents.extend(
        skill_document(child_id, fact)
        for fact in skills
        if fact.state != "not_started" or fact.total_attempts > 0
    )
    documents.extend(session_document(child_id, fact) for fact in sessions)
    documents.extend(
        confusion_document(child_id, fact)
        for fact in confusions
        if fact.occurrences >= MIN_CONFUSION_OCCURRENCES
    )
    documents.extend(milestone_document(child_id, fact) for fact in milestones)
    return documents


def forbidden_fields_present(documents: Sequence[MemoryDocument]) -> list[str]:
    """Which forbidden keys appear in a built corpus. Empty is the only pass."""
    found: list[str] = []
    for document in documents:
        for key in document.metadata:
            if key.lower() in FORBIDDEN_DOCUMENT_FIELDS:
                found.append(f"{document.doc_id}.{key}")
    return sorted(found)


__all__ = [
    "CATEGORY_AR",
    "COMMS_AR",
    "FORBIDDEN_DOCUMENT_FIELDS",
    "MIN_CONFUSION_OCCURRENCES",
    "STATE_AR",
    "ConfusionFact",
    "DocumentKind",
    "MemoryDocument",
    "MilestoneFact",
    "ProfileFact",
    "SessionFactRow",
    "SkillFact",
    "build_corpus",
    "confusion_document",
    "forbidden_fields_present",
    "milestone_document",
    "profile_document",
    "session_document",
    "skill_document",
]
