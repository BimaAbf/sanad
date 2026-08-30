"""Is the curriculum completable without speaking?

docs/04d §7 last row: *"Consent `voice_asr` absent → expressive tasks never
appear; the curriculum runs receptive-only and is complete on its own."*

That sentence is a load-bearing product claim, not a fallback note. A family
that declines microphone consent — which is the default, and a reasonable
default — must get the entire product, not a degraded one. So it is checked
mechanically over all 88 skills rather than asserted in prose.

Pure. No I/O.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

RECEPTIVE = "receptive"
EXPRESSIVE = "expressive"


@dataclass(frozen=True, slots=True)
class TemplateModality:
    code: str
    modality: str
    min_tier: int


@dataclass(frozen=True, slots=True)
class SkillTier:
    code: str
    difficulty_tier: int


def usable_templates(
    skill: SkillTier, templates: Sequence[TemplateModality], *, modality: str
) -> list[str]:
    return [
        template.code
        for template in templates
        if template.modality == modality and template.min_tier <= skill.difficulty_tier
    ]


def receptive_gaps(skills: Sequence[SkillTier], templates: Sequence[TemplateModality]) -> list[str]:
    """Skills with no receptive activity available at their tier.

    Non-empty means a child whose family declined microphone consent cannot
    reach part of the curriculum — which would make the consent toggle a
    paywall on learning, and it must not be one.
    """
    return [
        skill.code for skill in skills if not usable_templates(skill, templates, modality=RECEPTIVE)
    ]


def expressive_only_skills(
    skills: Sequence[SkillTier], templates: Sequence[TemplateModality]
) -> list[str]:
    """Skills reachable *only* by speaking. Must always be empty."""
    return [
        skill.code
        for skill in skills
        if usable_templates(skill, templates, modality=EXPRESSIVE)
        and not usable_templates(skill, templates, modality=RECEPTIVE)
    ]
