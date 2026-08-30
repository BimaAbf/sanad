"""Building the activity a guarded decision asked for. Pure and deterministic.

The decision says "teach `color_red`, selection, difficulty 2, demonstrate
first". This module turns that into the document the child's device renders and
the answer key the server keeps. It reads no database and calls no model: the
repository hands it rows, it hands back an `Activity`.

Deterministic given a seed, and the seed is `(session_id, ordinal)`. Two
reasons that matters more than usual here: a caregiver reporting "it showed the
wrong picture" can have the exact activity rebuilt, and a re-requested activity
is byte-identical to the one already on screen rather than a new arrangement of
the same cards under a child's finger.

The Arabic instructions are PLACEHOLDER, like everything else the agent wrote.
→ REVIEW-QUEUE.md #6
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from seeds.tracing import reference_path

from app.modules.tutor.domain.contract import (
    Activity,
    ActivityType,
    AnswerKey,
    Bin,
    Option,
    Presentation,
)
from app.modules.tutor.domain.drawing import PASS_THRESHOLD

#: docs/06 §4 — instructions are five words or fewer once the label is in.
INSTRUCTIONS: dict[ActivityType, str] = {
    ActivityType.SELECT_PICTURE: "وريني {label}",
    ActivityType.LISTEN_CHOOSE: "فين {label}؟",
    ActivityType.MATCH_PAIR: "لاقي زيها",
    ActivityType.COUNT_OBJECTS: "عدّ معايا",
    ActivityType.SORT_CATEGORY: "حطها في مكانها",
    ActivityType.ORDER_SEQUENCE: "رتبهم بالترتيب",
    ActivityType.SPEAK_WORD: "قول {label}",
    ActivityType.TRACE_LETTER: "اكتب {label}",
}

#: The "watch me first" line, shown only when the decision asked for it.
DEMONSTRATION_AR = "بص الأول… أنا هعملها"

#: Caregiver-facing labels for the sorting bins, per skill category.
CATEGORY_LABEL_AR: dict[str, str] = {
    "colors": "ألوان",
    "body_parts": "جسمي",
    "social": "كلام",
    "household": "البيت",
    "numbers": "أرقام",
    "letters": "حروف",
}

#: How many things are on screen, by difficulty. Capped by the child's own
#: `max_choices`, which is an accessibility setting and always wins.
CHOICES_FOR_DIFFICULTY: dict[int, int] = {1: 2, 2: 2, 3: 3, 4: 4, 5: 4}

#: How many cards a sorting activity uses, and how many a sequence uses.
SORT_CARDS = 3
SEQUENCE_LENGTH = 3


@dataclass(frozen=True, slots=True)
class SkillRow:
    """One row of `skills`, as the domain needs it. No SQLAlchemy in here."""

    skill_id: str
    code: str
    category: str
    label_ar: str
    label_egy: str
    alt_text_ar: str
    intro_order: int


def _rng(seed: int) -> Callable[[], float]:
    """mulberry32, the same generator the web bundle uses.

    A named algorithm rather than `random.Random`, so a session rebuilt in
    Python and a session rebuilt in the browser produce the same arrangement,
    and so the sequence cannot change under a Python upgrade.
    """
    state = seed & 0xFFFFFFFF

    def next_float() -> float:
        nonlocal state
        state = (state + 0x6D2B79F5) & 0xFFFFFFFF
        t = state
        t = (t ^ (t >> 15)) * (t | 1) & 0xFFFFFFFF
        t ^= (t + ((t ^ (t >> 7)) * (t | 61) & 0xFFFFFFFF)) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296.0

    return next_float


def shuffled[T](items: Sequence[T], seed: int) -> list[T]:
    """Fisher-Yates with the seeded generator. Stable for a given seed.

    Generic, so a caller gets its own element type back rather than `object`.
    The first version returned `list[object]` and every call site had to cast,
    which is a type annotation apologising for itself.
    """
    result = list(items)
    rand = _rng(seed)
    for index in range(len(result) - 1, 0, -1):
        swap = int(rand() * (index + 1))
        result[index], result[swap] = result[swap], result[index]
    return result


def _option(row: SkillRow, index: int, *, repeat: int = 1) -> Option:
    """One tappable card.

    Positional ids rather than skill codes: a client that logs the payload must
    not be able to read the answer out of an id, and `opt-2` says nothing about
    which card is right.
    """
    return Option(
        option_id=f"opt-{index}",
        skill_code=row.code,
        label_ar=row.label_ar,
        alt_ar=row.alt_text_ar,
        category=row.category,
        repeat=repeat,
    )


def choice_count_for(difficulty: int, max_choices: int) -> int:
    """Never more than the child's configured maximum.

    A choice count a child cannot handle is the single most common cause of a
    session that feels like a test, and it is an accessibility setting rather
    than a difficulty knob — so it caps the difficulty rather than the other
    way round.
    """
    wanted = CHOICES_FOR_DIFFICULTY.get(difficulty, 2)
    return max(2, min(wanted, max(max_choices, 2)))


def numeral_value(code: str) -> int:
    """`num_7` -> 7. Zero when the code is not a numeral."""
    _, _, suffix = code.partition("_")
    return int(suffix) if suffix.isdigit() else 0


def build(
    *,
    activity_type: ActivityType,
    target: SkillRow,
    pool: Sequence[SkillRow],
    difficulty: int,
    modality: str,
    strategy: str,
    support_level: str,
    prompt_level: str,
    demonstrate_first: bool,
    max_choices: int,
    seed: int,
    caregiver_confirm_allowed: bool = True,
) -> Activity:
    """One activity, fully built. `pool` is the distractor pool from the repo."""
    count = choice_count_for(difficulty, max_choices)
    label = target.label_egy or target.label_ar
    instruction = INSTRUCTIONS[activity_type].format(label=label)
    demonstration = DEMONSTRATION_AR if demonstrate_first else ""

    def common(presentation: Presentation, answer_key: AnswerKey) -> Activity:
        return Activity(
            activity_type=activity_type,
            skill_code=target.code,
            difficulty=difficulty,
            modality=modality,
            strategy=strategy,
            support_level=support_level,
            prompt_level=prompt_level,
            choice_count=count,
            presentation=presentation,
            answer_key=answer_key,
        )

    match activity_type:
        case ActivityType.SELECT_PICTURE | ActivityType.LISTEN_CHOOSE | ActivityType.MATCH_PAIR:
            rows = [target, *list(pool)[: count - 1]]
            ordered = shuffled(rows, seed)
            options = tuple(_option(row, index) for index, row in enumerate(ordered))
            answer = next(o for o in options if o.skill_code == target.code)
            sample = (
                Option(
                    option_id="sample",
                    skill_code=target.code,
                    label_ar=target.label_ar,
                    alt_ar=target.alt_text_ar,
                    category=target.category,
                )
                if activity_type is ActivityType.MATCH_PAIR
                else None
            )
            return common(
                Presentation(
                    instruction_ar=instruction,
                    spoken_ar=label,
                    demonstration_ar=demonstration,
                    options=options,
                    sample=sample,
                    # A listening task with the words written on the cards is a
                    # reading task. Hiding the labels is what makes the audio
                    # the only route to the answer.
                    hide_labels=activity_type is ActivityType.LISTEN_CHOOSE,
                ),
                AnswerKey(option_id=answer.option_id),
            )

        case ActivityType.COUNT_OBJECTS:
            value = numeral_value(target.code)
            # The numerals the child chooses between. `pool` is numerals here,
            # so the distractors are neighbouring numbers, which is the
            # discrimination the activity is about.
            rows = [target, *list(pool)[: count - 1]]
            ordered = shuffled(rows, seed)
            options = tuple(_option(row, index) for index, row in enumerate(ordered))
            answer = next(o for o in options if o.skill_code == target.code)
            return common(
                Presentation(
                    instruction_ar=instruction,
                    spoken_ar=label,
                    demonstration_ar=demonstration,
                    options=options,
                    object_count=value,
                ),
                AnswerKey(option_id=answer.option_id, count=value),
            )

        case ActivityType.SORT_CATEGORY:
            others = [row for row in pool if row.category != target.category]
            same = [row for row in pool if row.category == target.category]
            if not others or not same:
                raise ValueError("sorting needs a card from another category")
            cards = [target, same[0], others[0]][:SORT_CARDS]
            ordered = shuffled(cards, seed)
            options = tuple(_option(row, index) for index, row in enumerate(ordered))
            bins = tuple(
                shuffled(
                    [
                        Bin(
                            bin_id=target.category,
                            label_ar=CATEGORY_LABEL_AR.get(target.category, target.category),
                            art_skill_code=same[0].code,
                        ),
                        Bin(
                            bin_id=others[0].category,
                            label_ar=CATEGORY_LABEL_AR.get(others[0].category, others[0].category),
                            art_skill_code=others[0].code,
                        ),
                    ],
                    seed + 1,
                )
            )
            assignments = {
                option.option_id: next(
                    row.category for row in ordered if row.code == option.skill_code
                )
                for option in options
            }
            return common(
                Presentation(
                    instruction_ar=instruction,
                    spoken_ar=label,
                    demonstration_ar=demonstration,
                    options=options,
                    bins=bins,
                ),
                AnswerKey(assignments=assignments),
            )

        case ActivityType.ORDER_SEQUENCE:
            neighbours = [row for row in pool if row.category == target.category]
            run = sorted([target, *neighbours], key=lambda row: row.intro_order)
            start = max(0, min(len(run) - SEQUENCE_LENGTH, run.index(target)))
            window = run[start : start + SEQUENCE_LENGTH]
            if len(window) < 2:
                raise ValueError("a sequence needs at least two items")
            correct_order = tuple(f"opt-{index}" for index in range(len(window)))
            options_in_order = tuple(_option(row, index) for index, row in enumerate(window))
            # The ids encode the correct order, so the presentation must be
            # shuffled or the answer is visible in the ids.
            presented = shuffled(options_in_order, seed)
            return common(
                Presentation(
                    instruction_ar=instruction,
                    spoken_ar=label,
                    demonstration_ar=demonstration,
                    options=tuple(presented),
                ),
                AnswerKey(order=correct_order),
            )

        case ActivityType.SPEAK_WORD:
            return common(
                Presentation(
                    instruction_ar=instruction,
                    spoken_ar=label,
                    demonstration_ar=demonstration,
                    options=(
                        Option(
                            option_id="opt-0",
                            skill_code=target.code,
                            label_ar=target.label_ar,
                            alt_ar=target.alt_text_ar,
                            category=target.category,
                        ),
                    ),
                    target_word_ar=target.label_ar,
                    caregiver_confirm_allowed=caregiver_confirm_allowed,
                ),
                AnswerKey(
                    option_id=target.code,
                    target_label_ar=target.label_ar,
                    target_label_egy=target.label_egy or target.label_ar,
                    # Every other word this child is being taught, so a
                    # recogniser hearing a DIFFERENT taught word cannot accept
                    # it as this one. docs/adr/011 §1.
                    competing_labels=tuple(row.label_ar for row in pool),
                ),
            )

        # `case _` for the last arm only — see the same note in
        # `domain/evaluate.py`. `ActivityType` is exhaustive, so a named final
        # arm leaves an untakeable fall-through branch behind it.
        case _:
            path = reference_path(target.code)
            if not path:
                raise ValueError(f"no tracing reference for {target.code}")
            return common(
                Presentation(
                    instruction_ar=instruction,
                    spoken_ar=label,
                    demonstration_ar=demonstration,
                    glyph_ar=target.label_ar,
                    reference_path=path,
                ),
                AnswerKey(reference_path=path, pass_threshold=PASS_THRESHOLD),
            )


__all__ = [
    "CATEGORY_LABEL_AR",
    "CHOICES_FOR_DIFFICULTY",
    "DEMONSTRATION_AR",
    "INSTRUCTIONS",
    "SkillRow",
    "build",
    "choice_count_for",
    "numeral_value",
    "shuffled",
]
