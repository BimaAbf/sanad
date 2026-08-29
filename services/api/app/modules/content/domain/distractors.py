"""Distractor selection — the errorless-learning rule.

From docs/04c §C05, and it is the reason the whole approach works:

    Wrong answers are not random. For a child with Down syndrome, a distractor
    that is too similar turns a comprehension task into a visual-discrimination
    task and manufactures failure.

So at tier 1-2 the wrong answers are maximally unlike the target: different
category, different colour family, different initial phoneme. "A red card never
sits beside an orange card at tier 1. A فرشة سنان never sits beside a مشط until
both are mastered."

At tier 3+ near-misses are introduced deliberately — but only among skills the
child has already mastered, so confusion is informative rather than defeating.

Pure. No I/O.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

#: Colours closer than this in perceptual distance may not appear together at
#: tier 1-2. docs/04c §C05 states the 0.4 threshold.
MIN_COLOUR_DISTANCE = 0.4

#: A distractor used in any of the last N activities is not reused.
RECENT_WINDOW = 3


@dataclass(frozen=True, slots=True)
class DistractorSkill:
    """The subset of a skill that distractor selection needs."""

    code: str
    category: str
    label_ar: str
    phonemes: str
    difficulty_tier: int
    is_active: bool = True
    colour: tuple[float, float, float] | None = None


def colour_distance(a: DistractorSkill, b: DistractorSkill) -> float:
    """Perceptual distance between two skills' colours.

    Non-colour skills are treated as maximally distant from everything: a
    toothbrush cannot be confused with a colour word by hue, so the colour rule
    has nothing to say about that pair and must not exclude it.
    """
    if a.colour is None or b.colour is None:
        return 1.0
    return math.dist(a.colour, b.colour)


def first_phoneme(skill: DistractorSkill) -> str:
    return skill.phonemes[:1] if skill.phonemes else ""


def visual_distance(a: DistractorSkill, b: DistractorSkill) -> float:
    """A crude stand-in for real visual dissimilarity.

    PLACEHOLDER: real perceptual distance needs the actual illustrations, which
    are open decision O3. Until then this combines colour distance with a
    word-length difference, which at least separates obviously-different items.
    Recorded in docs/adr/008-curriculum.md.
    """
    length_difference = abs(len(a.label_ar) - len(b.label_ar)) / 12.0
    return colour_distance(a, b) * 0.7 + min(length_difference, 1.0) * 0.3


def choose_distractors(
    target: DistractorSkill,
    pool: Sequence[DistractorSkill],
    *,
    count: int,
    tier: int,
    mastered: frozenset[str] = frozenset(),
    recent: Sequence[str] = (),
) -> list[DistractorSkill]:
    """Wrong answers for one activity, in presentation order.

    Returns fewer than `count` rather than relaxing the contrast rules if the
    pool cannot supply enough. A short activity is a content-authoring problem
    to be surfaced; a too-similar distractor is a child being set up to fail.
    """
    candidates = [skill for skill in pool if skill.is_active and skill.code != target.code]

    if tier <= 2:
        # Maximum contrast.
        candidates = [
            skill
            for skill in candidates
            if skill.category != target.category
            and colour_distance(skill, target) > MIN_COLOUR_DISTANCE
            and first_phoneme(skill) != first_phoneme(target)
        ]
        candidates.sort(key=lambda s: (-visual_distance(s, target), s.code))
    else:
        # Near-misses, but only among skills already mastered.
        near = [skill for skill in candidates if skill.code in mastered]
        candidates = near or candidates
        candidates.sort(key=lambda s: (visual_distance(s, target), s.code))

    recent_set = set(recent[-RECENT_WINDOW * 4 :])
    fresh = [skill for skill in candidates if skill.code not in recent_set]
    # If avoiding recent items would leave nothing, fall back to the full
    # ordering: repeating a distractor is mildly stale, but an activity with no
    # wrong answer at all is broken.
    chosen = fresh or candidates
    return chosen[:count]
