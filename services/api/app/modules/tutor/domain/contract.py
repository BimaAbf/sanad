"""The activity contract — one shape for every kind of activity.

Eight activity types, one schema. That is the whole point of this module: the
child app renders a component per `activity_type`, but it parses ONE document,
submits ONE shape, and reads ONE authoritative result. Eight disconnected
lesson architectures is the failure this exists to prevent.

Two invariants hold everywhere below and are the reason the module is split the
way it is:

**`Presentation` never contains the answer.** It is exactly what is serialised
to the child's device. `AnswerKey` is the server's half and is stored in a
column the client is never sent. A client cannot mark itself correct because it
does not have the information to.

**The type is closed.** `ActivityType` is a `StrEnum`, the database has the same
list as a CHECK constraint, and the AI guardrail repairs anything outside it.
An activity type nobody implemented is a blank screen for a child.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ActivityType(StrEnum):
    """The eight, in the priority order the specification gives them."""

    #: Selection — hear a word, point at the picture. Half of every session.
    SELECT_PICTURE = "select_picture"
    #: Counting — how many things are there.
    COUNT_OBJECTS = "count_objects"
    #: Matching — find the one that is the same as this.
    MATCH_PAIR = "match_pair"
    #: Listening — the same shape as selection with the written labels removed,
    #: so the only route to the answer is through the audio.
    LISTEN_CHOOSE = "listen_choose"
    #: Speaking — say the word.
    SPEAK_WORD = "speak_word"
    #: Sorting — put each card in the bin it belongs to.
    SORT_CATEGORY = "sort_category"
    #: Sequence — put these in order.
    ORDER_SEQUENCE = "order_sequence"
    #: Drawing / tracing — trace the letter.
    TRACE_LETTER = "trace_letter"


class ResponseKind(StrEnum):
    CHOICE = "choice"
    COUNT = "count"
    SORT = "sort"
    SEQUENCE = "sequence"
    SPEECH = "speech"
    STROKES = "strokes"
    NO_RESPONSE = "no_response"


#: What a type expects back. A response of the wrong kind is a client bug, and
#: the evaluator refuses it rather than guessing what was meant.
EXPECTED_RESPONSE: dict[ActivityType, ResponseKind] = {
    ActivityType.SELECT_PICTURE: ResponseKind.CHOICE,
    ActivityType.LISTEN_CHOOSE: ResponseKind.CHOICE,
    ActivityType.MATCH_PAIR: ResponseKind.CHOICE,
    ActivityType.COUNT_OBJECTS: ResponseKind.COUNT,
    ActivityType.SORT_CATEGORY: ResponseKind.SORT,
    ActivityType.ORDER_SEQUENCE: ResponseKind.SEQUENCE,
    ActivityType.SPEAK_WORD: ResponseKind.SPEECH,
    ActivityType.TRACE_LETTER: ResponseKind.STROKES,
}

#: The modality each type exercises. `expressive` is the effortful one and the
#: planner never puts two in a row.
MODALITY_OF: dict[ActivityType, str] = {
    ActivityType.SELECT_PICTURE: "receptive",
    ActivityType.LISTEN_CHOOSE: "receptive",
    ActivityType.MATCH_PAIR: "receptive",
    ActivityType.COUNT_OBJECTS: "receptive",
    ActivityType.SORT_CATEGORY: "receptive",
    ActivityType.ORDER_SEQUENCE: "receptive",
    ActivityType.SPEAK_WORD: "expressive",
    ActivityType.TRACE_LETTER: "productive",
}

#: Which skill categories each type can teach.
#:
#: `sort_category` is not offered for letters or numbers: "is أ a letter or a
#: colour" is a question about the curriculum's filing system rather than about
#: the alphabet. `count_objects` needs a number to count to. `trace_letter`
#: needs a reference glyph, which exists for letters and digits.
SUPPORTED_CATEGORIES: dict[ActivityType, frozenset[str]] = {
    ActivityType.SELECT_PICTURE: frozenset(
        {"letters", "numbers", "colors", "body_parts", "household", "social"}
    ),
    ActivityType.LISTEN_CHOOSE: frozenset(
        {"letters", "numbers", "colors", "body_parts", "household", "social"}
    ),
    ActivityType.MATCH_PAIR: frozenset(
        {"letters", "numbers", "colors", "body_parts", "household", "social"}
    ),
    ActivityType.SPEAK_WORD: frozenset(
        {"letters", "numbers", "colors", "body_parts", "household", "social"}
    ),
    ActivityType.COUNT_OBJECTS: frozenset({"numbers"}),
    ActivityType.SORT_CATEGORY: frozenset({"colors", "body_parts", "household", "social"}),
    ActivityType.ORDER_SEQUENCE: frozenset({"numbers", "letters"}),
    ActivityType.TRACE_LETTER: frozenset({"letters", "numbers"}),
}

#: The type used whenever a chosen one cannot be delivered. Selection works for
#: every skill in the catalogue and needs nothing from the device beyond a tap.
SAFE_DEFAULT = ActivityType.SELECT_PICTURE

#: Which teaching modality each activity type exercises.
#:
#: The brain reasons in teaching terms — visual, audio, expressive, productive —
#: and the `modality` ENUM in the database speaks in
#: receptive/expressive/productive. They are NOT the same vocabulary: pointing
#: at a picture and listening to a word are both `receptive`, and a child can be
#: much better at one than the other. Conflating them made `visual_strong` in
#: the deterministic fallback permanently false, because nothing ever put a key
#: called "visual" into the accuracy map.
TEACHING_MODALITY: dict[ActivityType, str] = {
    ActivityType.SELECT_PICTURE: "visual",
    ActivityType.MATCH_PAIR: "visual",
    ActivityType.SORT_CATEGORY: "visual",
    ActivityType.ORDER_SEQUENCE: "visual",
    ActivityType.COUNT_OBJECTS: "visual",
    ActivityType.LISTEN_CHOOSE: "audio",
    ActivityType.SPEAK_WORD: "expressive",
    ActivityType.TRACE_LETTER: "productive",
}

#: Types that need something the deployment or the family may not have granted:
#: a microphone, and a surface big enough to draw on.
NEEDS_MICROPHONE = frozenset({ActivityType.SPEAK_WORD})
NEEDS_DRAWING_SURFACE = frozenset({ActivityType.TRACE_LETTER})


@dataclass(frozen=True, slots=True)
class Option:
    """One tappable thing. Carries no correctness flag — deliberately."""

    option_id: str
    skill_code: str
    label_ar: str
    alt_ar: str
    #: `colors` renders a swatch, everything else renders its drawing. Passed so
    #: the client never has to know the curriculum's categories.
    category: str = ""
    #: `count_objects` repeats one drawing this many times.
    repeat: int = 1

    def as_json(self) -> dict[str, Any]:
        return {
            "option_id": self.option_id,
            "skill_code": self.skill_code,
            "label_ar": self.label_ar,
            "alt_ar": self.alt_ar,
            "category": self.category,
            "repeat": self.repeat,
        }


@dataclass(frozen=True, slots=True)
class Bin:
    bin_id: str
    label_ar: str
    art_skill_code: str

    def as_json(self) -> dict[str, Any]:
        return {
            "bin_id": self.bin_id,
            "label_ar": self.label_ar,
            "art_skill_code": self.art_skill_code,
        }


@dataclass(frozen=True, slots=True)
class Presentation:
    """Everything the child's device is given, and nothing else.

    `instruction_ar` is short Egyptian Arabic. `demonstration_ar` is the
    "watch me first" line and is present only when the decision asked for a
    demonstration, so the client never has to decide whether to show one.
    """

    instruction_ar: str
    #: What Nour says out loud. Often the word alone rather than the sentence.
    spoken_ar: str
    #: Shown only when the strategy is demonstrate-then-test.
    demonstration_ar: str = ""
    options: tuple[Option, ...] = ()
    bins: tuple[Bin, ...] = ()
    #: `match_pair`: the card being matched against.
    sample: Option | None = None
    #: `trace_letter`: the glyph and its reference path, in a unit box.
    glyph_ar: str = ""
    reference_path: tuple[tuple[tuple[float, float], ...], ...] = ()
    #: `count_objects`: how many objects are on screen.
    object_count: int = 0
    #: `speak_word`: the word to say, and whether a caregiver may confirm it.
    target_word_ar: str = ""
    caregiver_confirm_allowed: bool = True
    #: Set when the child app must hide written labels (listening tasks).
    hide_labels: bool = False

    def as_json(self) -> dict[str, Any]:
        return {
            "instruction_ar": self.instruction_ar,
            "spoken_ar": self.spoken_ar,
            "demonstration_ar": self.demonstration_ar,
            "options": [option.as_json() for option in self.options],
            "bins": [bin_.as_json() for bin_ in self.bins],
            "sample": self.sample.as_json() if self.sample else None,
            "glyph_ar": self.glyph_ar,
            "reference_path": [[list(point) for point in stroke] for stroke in self.reference_path],
            "object_count": self.object_count,
            "target_word_ar": self.target_word_ar,
            "caregiver_confirm_allowed": self.caregiver_confirm_allowed,
            "hide_labels": self.hide_labels,
        }


@dataclass(frozen=True, slots=True)
class AnswerKey:
    """The server's half. Never serialised to a client.

    Every field is optional because one type uses one of them; keeping them on
    one dataclass rather than a union is what lets `evaluate` be a single
    function with one signature, which is what makes it testable as a whole.
    """

    #: `select_picture`, `listen_choose`, `match_pair`.
    option_id: str = ""
    #: `count_objects`.
    count: int = 0
    #: `sort_category`: option_id -> bin_id.
    assignments: dict[str, str] = field(default_factory=dict)
    #: `order_sequence`: the option ids in their correct order.
    order: tuple[str, ...] = ()
    #: `speak_word`.
    target_label_ar: str = ""
    target_label_egy: str = ""
    target_phonemes: str = ""
    competing_labels: tuple[str, ...] = ()
    #: `trace_letter`.
    reference_path: tuple[tuple[tuple[float, float], ...], ...] = ()
    pass_threshold: float = 0.0

    def as_json(self) -> dict[str, Any]:
        return {
            "option_id": self.option_id,
            "count": self.count,
            "assignments": dict(self.assignments),
            "order": list(self.order),
            "target_label_ar": self.target_label_ar,
            "target_label_egy": self.target_label_egy,
            "target_phonemes": self.target_phonemes,
            "competing_labels": list(self.competing_labels),
            "reference_path": [[list(p) for p in stroke] for stroke in self.reference_path],
            "pass_threshold": self.pass_threshold,
        }

    @staticmethod
    def from_json(payload: dict[str, Any]) -> AnswerKey:
        return AnswerKey(
            option_id=str(payload.get("option_id", "")),
            count=int(payload.get("count", 0)),
            assignments={str(k): str(v) for k, v in dict(payload.get("assignments", {})).items()},
            order=tuple(str(value) for value in payload.get("order", [])),
            target_label_ar=str(payload.get("target_label_ar", "")),
            target_label_egy=str(payload.get("target_label_egy", "")),
            target_phonemes=str(payload.get("target_phonemes", "")),
            competing_labels=tuple(str(v) for v in payload.get("competing_labels", [])),
            reference_path=tuple(
                tuple((float(p[0]), float(p[1])) for p in stroke)
                for stroke in payload.get("reference_path", [])
            ),
            pass_threshold=float(payload.get("pass_threshold", 0.0)),
        )


@dataclass(frozen=True, slots=True)
class Activity:
    """A built activity, before it is persisted."""

    activity_type: ActivityType
    skill_code: str
    difficulty: int
    modality: str
    strategy: str
    support_level: str
    prompt_level: str
    choice_count: int
    presentation: Presentation
    answer_key: AnswerKey


def supports(activity_type: ActivityType, category: str) -> bool:
    return category in SUPPORTED_CATEGORIES[activity_type]


__all__ = [
    "EXPECTED_RESPONSE",
    "MODALITY_OF",
    "NEEDS_DRAWING_SURFACE",
    "NEEDS_MICROPHONE",
    "SAFE_DEFAULT",
    "SUPPORTED_CATEGORIES",
    "TEACHING_MODALITY",
    "Activity",
    "ActivityType",
    "AnswerKey",
    "Bin",
    "Option",
    "Presentation",
    "ResponseKind",
    "supports",
]
