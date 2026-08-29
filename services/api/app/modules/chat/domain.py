"""Chat domain — two surfaces, two completely different contracts.

================================================================================
WHY THE CHILD SURFACE DOES NOT GENERATE TEXT
================================================================================
The caregiver assistant writes prose. The child-facing one does not, and the
difference is not a matter of degree.

Three constraints make free generation to a child the wrong design here, and
each of them stands alone:

1. **The child app runs offline.** docs/04e §C13 has the whole session preloaded
   into the Cache API before the first prompt plays, so that a dropped
   connection is invisible mid-activity. A reply that has to be generated is a
   reply that cannot arrive when the network is down -- which is precisely when
   a child is mid-sentence waiting for one.
2. **Nour's voice is frozen by design.** Assumption C7: voice consistency is a
   comprehension aid for this population, which is why docs/12 §3 renders the
   corpus ahead of time rather than synthesising at runtime. Generated text has
   no rendered audio, so it either arrives in a different voice or arrives
   silent.
3. **Nothing unreviewed should be said to a child with a communication
   disability who is learning these exact words.** A generated sentence is
   unreviewed by construction.

So the child surface is a **closed set**. The model's entire job is to pick one
id from `CHILD_PHRASES` -- a classification, not a generation -- and
`enforce_enum` rejects anything else. Every phrase in that table is written
once, reviewable in one place, renderable to audio ahead of time, and available
offline. If the model is unavailable the fallback picks a phrase deterministically
and the child notices nothing.

This is the same architecture as every other AI decision point in the product:
the model reorders or selects within a set the deterministic layer produced, and
it can never add to it.
================================================================================
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.guardrails.layers import SafetyFinding, screen_input


class Surface(StrEnum):
    CAREGIVER = "caregiver"
    CHILD = "child"


class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class TurnOutcome(StrEnum):
    OK = "ok"
    #: The keyword pre-filter found a red flag. The model is not called at all.
    ESCALATED = "escalated"
    #: The model answered and a guardrail blocked what it said.
    BLOCKED = "blocked"
    #: No model was reachable. A written fallback answered.
    FALLBACK = "fallback"


#: docs/04e §C13 caps a play session at ten minutes; a child-surface exchange
#: that runs longer than the session it sits inside is a bug in the caller.
MAX_CHILD_TURNS_PER_SESSION = 12

#: The caregiver assistant keeps this many prior turns in context. Six is three
#: exchanges -- enough for "and what about his brother?" to resolve, short
#: enough that the transcript never becomes the bulk of the prompt on a
#: provider with no caching (docs/12 §1).
CAREGIVER_HISTORY_TURNS = 6

MAX_MESSAGE_CHARS = 800


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Role
    text_ar: str
    created_at: dt.datetime | None = None
    grounded_in: tuple[str, ...] = ()
    outcome: TurnOutcome = TurnOutcome.OK


# --- the child surface's closed set -----------------------------------------


@dataclass(frozen=True, slots=True)
class ChildPhrase:
    """One thing Nour is allowed to say.

    `audio_key` is the path into the pre-rendered corpus. It is populated here
    even though no renderer has run yet, because the alternative -- adding the
    field when the renderer lands -- means the ids and the audio files get named
    by two different people at two different times.
    """

    phrase_id: str
    text_ar: str
    audio_key: str
    #: When this phrase is the right answer, in one line, for the model.
    when_ar: str


CHILD_PHRASES: tuple[ChildPhrase, ...] = (
    ChildPhrase(
        "greet",
        "أهلاً بيك! جاهز نلعب مع بعض؟",
        "nour/greet.opus",
        "أول ما الطفل يبدأ الكلام أو يسلّم",
    ),
    ChildPhrase(
        "encourage_try",
        "تعالى نجرّب تاني مع بعض.",
        "nour/encourage_try.opus",
        "لما الطفل يقول إنه مش عارف أو يسكت",
    ),
    ChildPhrase(
        "celebrate",
        "برافو عليك! شاطر أوي.",
        "nour/celebrate.opus",
        "لما الطفل يجاوب صح أو يبان مبسوط",
    ),
    ChildPhrase(
        "repeat_prompt",
        "هقولها تاني وانت تسمع.",
        "nour/repeat_prompt.opus",
        "لما الطفل يطلب يسمع تاني",
    ),
    ChildPhrase(
        "rest",
        "تعبت؟ خلاص نرتاح شوية.",
        "nour/rest.opus",
        "لما الطفل يقول إنه تعبان أو عايز يبطل",
    ),
    ChildPhrase(
        "call_caregiver",
        "خلينا ننادي ماما أو بابا.",
        "nour/call_caregiver.opus",
        "لما الطفل يبان زعلان أو يطلب حد كبير",
    ),
    ChildPhrase(
        "not_understood",
        "مش سامعك كويس. قولها تاني؟",
        "nour/not_understood.opus",
        "لما مفيش كلام واضح، أو الرد مش مفهوم",
    ),
)

CHILD_PHRASES_BY_ID: dict[str, ChildPhrase] = {
    phrase.phrase_id: phrase for phrase in CHILD_PHRASES
}

#: The phrase used when no model answered. Not "greet": a fallback that greets
#: a child mid-conversation reads as Nour having forgotten them.
CHILD_FALLBACK_PHRASE = "not_understood"

#: The phrase used when the input screen finds a red flag on the child surface.
#: A child saying something distressing is not something Nour answers.
CHILD_ESCALATION_PHRASE = "call_caregiver"


def child_phrase_ids() -> list[str]:
    return [phrase.phrase_id for phrase in CHILD_PHRASES]


def resolve_child_phrase(phrase_id: str | None) -> ChildPhrase:
    """Always returns a phrase. An unknown id is the fallback, never an error."""
    if phrase_id and phrase_id in CHILD_PHRASES_BY_ID:
        return CHILD_PHRASES_BY_ID[phrase_id]
    return CHILD_PHRASES_BY_ID[CHILD_FALLBACK_PHRASE]


# --- the caregiver surface's written fallbacks ------------------------------

#: Shown when no model answered a caregiver. It says what happened rather than
#: producing a generic sentence that reads like an answer -- a caregiver who
#: thinks they got an answer will not ask again.
CAREGIVER_FALLBACK_AR = (
    "مش قادر أجاوب دلوقتي. تقدر تشوف تفاصيل تقدّم طفلك من صفحة المهارات."
)

#: Shown when the input screen finds a red flag. The model is never called.
#: docs/04e: red-flag input bypasses the AI entirely and goes to a human.
CAREGIVER_ESCALATION_AR = (
    "الكلام ده مهم ومحتاج حد متخصص يسمعه، مش تطبيق. "
    "لو فيه خطر دلوقتي كلّم الطوارئ، وغير كده كلّم دكتور طفلك."
)

#: Shown when a guardrail blocked what the model said.
CAREGIVER_BLOCKED_AR = (
    "الرد اللي طلع مكانش مناسب فمنعناه. لو السؤال مهم، اسأل دكتور طفلك."
)


@dataclass(frozen=True, slots=True)
class InputScreen:
    """The result of screening one incoming message."""

    findings: tuple[SafetyFinding, ...]
    escalate: bool

    @property
    def categories(self) -> tuple[str, ...]:
        return tuple(sorted({finding.category for finding in self.findings}))


#: A finding at or above this severity bypasses the model entirely.
ESCALATION_SEVERITY = 2


def screen(text: str) -> InputScreen:
    """Red-flag screening on the way in.

    This runs on **both** surfaces and before any model call, which is the
    ordering docs/04e requires: red-flag input goes to a human rather than to a
    model, and a screen that ran after generation would already have paid to
    have the model reason about it.
    """
    findings = tuple(screen_input(text))
    return InputScreen(
        findings=findings,
        escalate=any(finding.severity >= ESCALATION_SEVERITY for finding in findings),
    )


def clip(text: str, *, limit: int = MAX_MESSAGE_CHARS) -> str:
    """Bound the input. A caregiver pasting a report is a real thing to do."""
    stripped = text.strip()
    return stripped[:limit]


def recent(
    messages: Sequence[ChatMessage], *, turns: int = CAREGIVER_HISTORY_TURNS
) -> list[dict[str, str]]:
    """Prior turns as the plain JSON the gateway serialises, oldest first."""
    return [
        {"role": message.role.value, "text": message.text_ar}
        for message in list(messages)[-turns:]
    ]


__all__ = [
    "CAREGIVER_BLOCKED_AR",
    "CAREGIVER_ESCALATION_AR",
    "CAREGIVER_FALLBACK_AR",
    "CAREGIVER_HISTORY_TURNS",
    "CHILD_ESCALATION_PHRASE",
    "CHILD_FALLBACK_PHRASE",
    "CHILD_PHRASES",
    "CHILD_PHRASES_BY_ID",
    "ESCALATION_SEVERITY",
    "MAX_CHILD_TURNS_PER_SESSION",
    "MAX_MESSAGE_CHARS",
    "ChatMessage",
    "ChildPhrase",
    "InputScreen",
    "Role",
    "Surface",
    "TurnOutcome",
    "child_phrase_ids",
    "clip",
    "recent",
    "resolve_child_phrase",
    "screen",
]
