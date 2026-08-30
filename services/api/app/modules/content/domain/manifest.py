"""Session manifest assembly.

The manifest is a complete, self-contained session: the child app preloads all
of it into the Cache API **before playing the first prompt**, then runs offline.
That is why a 30-second network drop is invisible to a child mid-activity.

Shape is docs/04c §C05. Pure — the service layer supplies resolved URLs.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

#: A manifest holds pre-signed URLs, so it must not outlive them.
DEFAULT_TTL = dt.timedelta(minutes=45)

#: docs/06 §4: instructions are <= 5 words, spoken and written and illustrated.
MAX_INSTRUCTION_WORDS = 5


@dataclass(frozen=True, slots=True)
class ChoiceEntry:
    skill_id: str
    image: str
    alt_ar: str
    correct: bool


@dataclass(frozen=True, slots=True)
class PromptRung:
    level: str
    audio: str
    highlight: str | None = None
    auto_select: bool = False


@dataclass(frozen=True, slots=True)
class ActivityEntry:
    id: str
    kind: str
    skill_id: str
    instruction_ar: str
    instruction_audio: str
    choices: tuple[ChoiceEntry, ...]
    prompt_ladder: tuple[PromptRung, ...]
    success_audio: tuple[str, ...]
    retry_audio: tuple[str, ...]
    est_seconds: int = 25


@dataclass(frozen=True, slots=True)
class ChildSettings:
    wait_time_ms: int
    max_choices: int
    audio_rate_pct: int
    calm_mode: bool


@dataclass(frozen=True, slots=True)
class SessionManifest:
    session_id: str
    child: ChildSettings
    activities: tuple[ActivityEntry, ...]
    closing_audio: str
    expires_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def instruction_word_count(instruction: str, label: str) -> int:
    """Words after {label} substitution."""
    return len(instruction.replace("{label}", label).split())


def build_prompt_ladder(
    *, gestural_audio: str, partial_audio: str, model_audio: str
) -> tuple[PromptRung, ...]:
    """The errorless ladder.

    The child never reaches a dead end: the last rung says the answer, highlights
    the correct choice and auto-selects it, so the child taps to celebrate. The
    result is recorded honestly as `full_model` (which contributes nothing to
    BKT) while the *experience* is a success. That gap between honest
    measurement and kind presentation is the core of the design.
    """
    return (
        PromptRung(level="gestural", audio=gestural_audio, highlight="correct"),
        PromptRung(level="partial_verbal", audio=partial_audio),
        PromptRung(level="full_model", audio=model_audio, auto_select=True),
    )


def build_manifest(
    *,
    session_id: str,
    child: ChildSettings,
    activities: Sequence[ActivityEntry],
    closing_audio: str,
    now: dt.datetime,
    ttl: dt.timedelta = DEFAULT_TTL,
) -> SessionManifest:
    return SessionManifest(
        session_id=session_id,
        child=child,
        activities=tuple(activities),
        closing_audio=closing_audio,
        expires_at=(now + ttl).isoformat(),
    )


def missing_media(manifest: SessionManifest) -> list[str]:
    """Every referenced asset that is empty or unset.

    Publishing is refused if this is non-empty (docs/04c §C05): a manifest with
    a missing audio file means a child sits in silence waiting for an
    instruction that never comes.
    """
    missing: list[str] = []
    for activity in manifest.activities:
        if not activity.instruction_audio:
            missing.append(f"{activity.id}:instruction_audio")
        for index, choice in enumerate(activity.choices):
            if not choice.image:
                missing.append(f"{activity.id}:choice[{index}].image")
            if not choice.alt_ar:
                missing.append(f"{activity.id}:choice[{index}].alt_ar")
        for rung in activity.prompt_ladder:
            if not rung.audio:
                missing.append(f"{activity.id}:ladder[{rung.level}].audio")
        if not activity.success_audio:
            missing.append(f"{activity.id}:success_audio")
        if not activity.retry_audio:
            missing.append(f"{activity.id}:retry_audio")
    if not manifest.closing_audio:
        missing.append("closing_audio")
    return missing


def validate(manifest: SessionManifest) -> list[str]:
    """Structural problems that must block a session. Empty means valid."""
    problems = [f"missing media: {item}" for item in missing_media(manifest)]

    for activity in manifest.activities:
        correct = [c for c in activity.choices if c.correct]
        if len(correct) != 1:
            problems.append(
                f"{activity.id}: has {len(correct)} correct choices, must have exactly 1"
            )
        if len(activity.choices) < 2:
            problems.append(f"{activity.id}: fewer than 2 choices")
        if len(activity.choices) > manifest.child.max_choices:
            problems.append(
                f"{activity.id}: {len(activity.choices)} choices exceeds this "
                f"child's max_choices of {manifest.child.max_choices}"
            )
        if len(activity.instruction_ar.split()) > MAX_INSTRUCTION_WORDS:
            problems.append(
                f"{activity.id}: instruction is longer than {MAX_INSTRUCTION_WORDS} words"
            )
        # The correct choice must be the one whose skill the activity is about.
        if correct and correct[0].skill_id != activity.skill_id:
            problems.append(f"{activity.id}: the correct choice is not the activity's own skill")
        codes = [c.skill_id for c in activity.choices]
        if len(codes) != len(set(codes)):
            problems.append(f"{activity.id}: the same skill appears twice among choices")

    return problems
