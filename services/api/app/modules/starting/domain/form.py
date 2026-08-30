"""The caregiver starting questionnaire, and what it derives. Pure, no I/O.

================================================================================
THIS IS INITIAL EVIDENCE, NOT A DIAGNOSIS AND NOT A TEST RESULT
================================================================================
A caregiver telling us where their child is gives SANAD somewhere to start. It
is the single best information available before the child has done anything —
and it is a parent's recollection, given on a phone, about their own child.
Three consequences are built into the derivation rather than left to good
intentions:

  * it can NEVER produce `mastered`. The highest band starts a skill at
    `practising` with p_known 0.65, and mastery needs 0.90 plus the evidence
    martingale over real independent attempts. There is no path from this form
    to a mastery badge, and there is a test asserting it.
  * it only sets a PRIOR. `learning/service.py` folds every real attempt over
    the top of it, so within a dozen attempts what the child actually did
    dominates what the caregiver reported — which is the correct direction of
    travel for any intake instrument.
  * it is stored as answered, alongside what was derived from it, so "why did
    SANAD start my child here" is answerable after the derivation changes.

The Arabic below is agent-written PLACEHOLDER and no clinician or native
Egyptian speaker has seen it. → REVIEW-QUEUE.md #6, #15
================================================================================

The specification names ten areas. Nine map onto something the product can act
on. `shapes` does not: the 88-skill curriculum has letters, numbers, colours,
body parts, household objects and social phrases, and no shapes at all. The
question is asked and the answer is stored — a caregiver who says their child
knows shapes has told us something true — but it derives no prior, because
there is no skill for it to be a prior of. That gap is recorded rather than
papered over with a category that does not exist. → REVIEW-QUEUE.md #15
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

FORM_VERSION = "starting-v1"

WATERMARK = "PLACEHOLDER — not reviewed by a clinician or a native speaker"


class Band(StrEnum):
    """The four answers. Ordered, and the order is the whole scale."""

    NOT_YET = "not_yet"
    STARTING = "starting"
    SOMETIMES = "sometimes"
    USUALLY = "usually"


BAND_ORDER: tuple[Band, ...] = (Band.NOT_YET, Band.STARTING, Band.SOMETIMES, Band.USUALLY)

BAND_LABEL_AR: dict[Band, str] = {
    Band.NOT_YET: "لسه لأ",
    Band.STARTING: "بيبتدي",
    Band.SOMETIMES: "أحيانا",
    Band.USUALLY: "غالبا أيوه",
}


def band_index(band: Band) -> int:
    return BAND_ORDER.index(band)


class Area(StrEnum):
    """The ten areas the specification names."""

    NUMBERS = "numbers"
    COUNTING = "counting"
    COLORS = "colors"
    SHAPES = "shapes"
    LETTERS = "letters"
    SIMPLE_WORDS = "simple_words"
    MATCHING = "matching"
    FOLLOWING_INSTRUCTIONS = "following_instructions"
    SPEECH = "speech"
    DRAWING = "drawing"


class Support(StrEnum):
    """The starting observations that are about HOW to teach, not WHAT."""

    DEMONSTRATION = "demonstration_helps"
    SPOKEN_INSTRUCTIONS = "follows_spoken"
    DURATION = "comfortable_minutes"
    SELECTION_SUPPORT = "selection_support"
    SPEAKING_COMFORT = "comfortable_speaking"


@dataclass(frozen=True, slots=True)
class Question:
    """One question. The example is what makes the answer valid.

    docs/04e §C12: parents cannot reliably answer abstract questions about their
    own child ("does he understand colour concepts?"), and can reliably answer
    concrete ones ("if you put a red cup and a blue cup down and ask for the red
    one, does he pick it up?"). Every question here is the second kind, and the
    example is part of the question rather than a nicety.
    """

    id: str
    area: Area | None
    support: Support | None
    prompt_ar: str
    example_ar: str
    #: The duration question has its own answers; everything else uses BAND.
    options: tuple[str, ...] = ()

    @property
    def uses_bands(self) -> bool:
        return not self.options


#: Minutes a child is comfortable for. Bounded by `learner_profiles`' CHECK.
DURATION_OPTIONS: tuple[tuple[str, int, str], ...] = (
    ("short", 4, "دقايق قليلة"),
    ("medium", 8, "حوالي ربع ساعة"),
    ("long", 14, "بيقعد أكتر"),
)


QUESTIONS: tuple[Question, ...] = (
    Question(
        id="q_colors",
        area=Area.COLORS,
        support=None,
        prompt_ar="بيعرف يوريك اللون لما تطلبيه؟",
        example_ar="لو حطيتي كوباية حمرا وكوباية زرقا وقلتيله هات الأحمر.",
    ),
    Question(
        id="q_numbers",
        area=Area.NUMBERS,
        support=None,
        prompt_ar="بيعرف الأرقام لما يشوفها؟",
        example_ar="لو وريتيه رقم ٢ ورقم ٥ وسألتي فين اتنين.",
    ),
    Question(
        id="q_counting",
        area=Area.COUNTING,
        support=None,
        prompt_ar="بيعد الحاجات؟",
        example_ar="لو حطيتي تلات معالق وقلتيله عدهم.",
    ),
    Question(
        id="q_shapes",
        area=Area.SHAPES,
        support=None,
        prompt_ar="بيفرق بين الأشكال؟",
        example_ar="لو وريتيه دايرة ومربع وسألتي فين الدايرة.",
    ),
    Question(
        id="q_letters",
        area=Area.LETTERS,
        support=None,
        prompt_ar="بيعرف حروف؟",
        example_ar="لو وريتيه حرف أ وحرف ب وسألتي فين الألف.",
    ),
    Question(
        id="q_words",
        area=Area.SIMPLE_WORDS,
        support=None,
        prompt_ar="بيعرف أسامي حاجات البيت؟",
        example_ar="لو قلتيله هات الكوباية وهي قدامه مع حاجة تانية.",
    ),
    Question(
        id="q_matching",
        area=Area.MATCHING,
        support=None,
        prompt_ar="بيلاقي الحاجة اللي زي التانية؟",
        example_ar="لو حطيتي جزمتين زي بعض وواحدة مختلفة وقلتيله لاقي زيها.",
    ),
    Question(
        id="q_instructions",
        area=Area.FOLLOWING_INSTRUCTIONS,
        support=Support.SPOKEN_INSTRUCTIONS,
        prompt_ar="بينفذ طلب بسيط من غير ما توريه؟",
        example_ar="لو قلتيله هات الفوطة وهو شايفها، من غير ما تشاوري.",
    ),
    Question(
        id="q_speech",
        area=Area.SPEECH,
        support=Support.SPEAKING_COMFORT,
        prompt_ar="بيقول كلمات لما تسأليه؟",
        example_ar="لو وريتيه كوباية وسألتي دي إيه، بيقول كلمة؟",
    ),
    Question(
        id="q_drawing",
        area=Area.DRAWING,
        support=None,
        prompt_ar="بيمسك القلم ويخربش أو يمشي على خط؟",
        example_ar="لو رسمتيله خط وقلتيله امشي عليه بالقلم.",
    ),
    Question(
        id="q_demonstration",
        area=None,
        support=Support.DEMONSTRATION,
        prompt_ar="بيتعلم أحسن لما توريه الأول؟",
        example_ar="لو عملتي الحاجة قدامه الأول وبعدين طلبتي منه يعملها.",
    ),
    Question(
        id="q_selection",
        area=None,
        support=Support.SELECTION_SUPPORT,
        prompt_ar="بيختار من حاجتين أسهل من الاختيار من أربعة؟",
        example_ar="لو حطيتي قدامه حاجتين بس بدل أربعة.",
    ),
    Question(
        id="q_duration",
        area=None,
        support=Support.DURATION,
        prompt_ar="بيقعد معاكي قد إيه قبل ما يزهق؟",
        example_ar="في أي لعبة أو نشاط بتعملوه مع بعض.",
        options=tuple(key for key, _minutes, _label in DURATION_OPTIONS),
    ),
)

QUESTION_BY_ID: dict[str, Question] = {question.id: question for question in QUESTIONS}


# --- what an answer derives -------------------------------------------------

#: The BKT prior each band starts a skill from.
#:
#: The top band is 0.65 and not 0.90, and that ceiling is the point: 0.90 is the
#: mastery threshold, so a form that could reach it would let a caregiver's
#: recollection put a mastery badge on a child's record. The evidence martingale
#: would still refuse, but relying on a second condition to catch the first
#: one's mistake is not a design.
BAND_PRIOR: dict[Band, float] = {
    Band.NOT_YET: 0.12,
    Band.STARTING: 0.25,
    Band.SOMETIMES: 0.45,
    Band.USUALLY: 0.65,
}

#: How many skills of a category are opened at that prior, in `intro_order`.
#: A caregiver who says their child usually knows their colours is saying the
#: first eight colours are somewhere in reach; one who says "not yet" is saying
#: start at the beginning.
BAND_SKILL_COUNT: dict[Band, int] = {
    Band.NOT_YET: 2,
    Band.STARTING: 3,
    Band.SOMETIMES: 5,
    Band.USUALLY: 8,
}

#: The mastery state a seeded skill starts in. Never `mastered`, never
#: `retained` — those are conclusions about evidence, and there is none yet.
BAND_STATE: dict[Band, str] = {
    Band.NOT_YET: "introduced",
    Band.STARTING: "introduced",
    Band.SOMETIMES: "practising",
    Band.USUALLY: "practising",
}

#: Which curriculum categories an area seeds. `shapes` seeds nothing — see the
#: module docstring. The cross-cutting areas (counting, matching, following
#: instructions, speech, drawing) are about HOW a child can be asked rather than
#: WHAT they know, so they set support flags instead.
AREA_CATEGORIES: dict[Area, tuple[str, ...]] = {
    Area.COLORS: ("colors",),
    Area.NUMBERS: ("numbers",),
    Area.LETTERS: ("letters",),
    Area.SIMPLE_WORDS: ("household", "body_parts"),
    Area.SPEECH: ("social",),
    Area.COUNTING: (),
    Area.MATCHING: (),
    Area.FOLLOWING_INSTRUCTIONS: (),
    Area.DRAWING: (),
    Area.SHAPES: (),
}


@dataclass(frozen=True, slots=True)
class SkillSeed:
    """One skill to open for this child, with the prior to open it at."""

    category: str
    rank: int
    prior: float
    state: str


@dataclass(frozen=True, slots=True)
class StartingProfile:
    """Everything the form derives. Persisted whole."""

    area_bands: dict[str, int] = field(default_factory=dict)
    seeds: tuple[SkillSeed, ...] = ()
    effective_support: str = "medium"
    effective_modality: str = "visual"
    demonstration_helps: bool = True
    follows_spoken: bool = True
    comfortable_speaking: bool = True
    comfortable_minutes: int = 8
    #: Areas the form asked about and could not act on, named rather than
    #: silently dropped.
    unmapped_areas: tuple[str, ...] = ()

    def as_json(self) -> dict[str, object]:
        return {
            "area_bands": dict(self.area_bands),
            "effective_support": self.effective_support,
            "effective_modality": self.effective_modality,
            "demonstration_helps": self.demonstration_helps,
            "follows_spoken": self.follows_spoken,
            "comfortable_speaking": self.comfortable_speaking,
            "comfortable_minutes": self.comfortable_minutes,
            "unmapped_areas": list(self.unmapped_areas),
        }


def is_complete(answers: dict[str, str]) -> bool:
    """Every question answered. The form is short; a partial one is not scored."""
    return all(question.id in answers for question in QUESTIONS)


def remaining(answers: dict[str, str]) -> tuple[Question, ...]:
    """The questions still to ask, in order. Only ever shrinks."""
    return tuple(question for question in QUESTIONS if question.id not in answers)


def derive(answers: dict[str, str]) -> StartingProfile:
    """Turn the answer log into a starting profile. Total and deterministic.

    Unanswered questions fall back to the middle of the scale rather than
    raising: a caregiver who skipped one has not made the rest unusable, and a
    profile that refuses to exist is worse for the child than one built from
    nine answers out of ten.
    """
    area_bands: dict[str, int] = {}
    seeds: list[SkillSeed] = []
    unmapped: list[str] = []

    for question in QUESTIONS:
        if question.area is None:
            continue
        band = _band(answers.get(question.id))
        area_bands[str(question.area)] = band_index(band)
        categories = AREA_CATEGORIES[question.area]
        if not categories:
            if question.area in (Area.SHAPES,):
                unmapped.append(str(question.area))
            continue
        for category in categories:
            for rank in range(BAND_SKILL_COUNT[band]):
                seeds.append(
                    SkillSeed(
                        category=category,
                        rank=rank,
                        prior=BAND_PRIOR[band],
                        state=BAND_STATE[band],
                    )
                )

    demonstration = _band(answers.get("q_demonstration"))
    spoken = _band(answers.get("q_instructions"))
    speaking = _band(answers.get("q_speech"))
    selection = _band(answers.get("q_selection"))

    # The average band across the areas that map to skills. A child a caregiver
    # reports as generally further along needs less scaffolding to start with,
    # and the runtime moves it from there on real evidence.
    mapped = [value for area, value in area_bands.items() if AREA_CATEGORIES[Area(area)]]
    average = sum(mapped) / len(mapped) if mapped else 1.0
    support = "high" if average < 1.0 else ("low" if average >= 2.5 else "medium")
    if band_index(selection) >= 2 and support == "low":
        # A caregiver who says two choices are easier than four is describing a
        # child who needs the field narrowed. That is a support need whatever
        # the rest of the form said, so it stops the support level bottoming
        # out at "low" for a child who is otherwise doing well.
        support = "medium"

    return StartingProfile(
        area_bands=area_bands,
        seeds=tuple(seeds),
        effective_support=support,
        # Visual unless the caregiver reports that spoken instructions land on
        # their own. This is a starting guess and the runtime replaces it with
        # measured per-modality accuracy as soon as there is any.
        effective_modality="audio" if band_index(spoken) >= 2 else "visual",
        demonstration_helps=band_index(demonstration) >= 2,
        follows_spoken=band_index(spoken) >= 2,
        comfortable_speaking=band_index(speaking) >= 1,
        comfortable_minutes=_minutes(answers.get("q_duration")),
        unmapped_areas=tuple(unmapped),
    )


def _band(value: str | None) -> Band:
    try:
        return Band(value or "")
    except ValueError:
        return Band.STARTING


def _minutes(value: str | None) -> int:
    for key, minutes, _label in DURATION_OPTIONS:
        if key == value:
            return minutes
    return 8


def question_payload() -> list[dict[str, object]]:
    """The form, as the client renders it. Options included so it has no copy."""
    payload: list[dict[str, object]] = []
    for question in QUESTIONS:
        options: list[dict[str, str]]
        if question.uses_bands:
            options = [{"id": str(band), "label_ar": BAND_LABEL_AR[band]} for band in BAND_ORDER]
        else:
            options = [{"id": key, "label_ar": label} for key, _minutes, label in DURATION_OPTIONS]
        payload.append(
            {
                "id": question.id,
                "area": str(question.area) if question.area else "",
                "prompt_ar": question.prompt_ar,
                "example_ar": question.example_ar,
                "options": options,
            }
        )
    return payload


__all__ = [
    "AREA_CATEGORIES",
    "BAND_LABEL_AR",
    "BAND_ORDER",
    "BAND_PRIOR",
    "BAND_SKILL_COUNT",
    "BAND_STATE",
    "DURATION_OPTIONS",
    "FORM_VERSION",
    "QUESTIONS",
    "QUESTION_BY_ID",
    "WATERMARK",
    "Area",
    "Band",
    "Question",
    "SkillSeed",
    "StartingProfile",
    "Support",
    "band_index",
    "derive",
    "is_complete",
    "question_payload",
    "remaining",
]
