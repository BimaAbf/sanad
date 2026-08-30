"""Session facts, computed deterministically from what actually happened.

Two audiences, one set of numbers.

The CHILD gets a completion, their stars and their achievements. No accuracy, no
comparison, no score — docs/04e §C13 has no failure state, and "you got 4 out of
7" is one however it is phrased.

The CAREGIVER gets the facts below, and a narrative built FROM them. The
narrative may be written by the model; the facts may not. `narrative_violations`
is what enforces that: every number in a generated summary must be a number this
module computed, or the template ships instead. A model that invents "she did
twelve activities" when she did seven is rejected, not corrected.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

#: Results that count as a success in the session totals. The same set the
#: reward rule uses, imported rather than restated so the caregiver report and
#: the sticker chart can never disagree about what "went well" means.
from app.modules.tutor.domain.rewards import REWARDED_RESULTS

#: Prompt levels that mean the child answered without help.
INDEPENDENT_LEVELS = frozenset({"independent"})


@dataclass(frozen=True, slots=True)
class AttemptFact:
    """One attempt, as the report needs it."""

    skill_code: str
    skill_label_ar: str
    activity_type: str
    result: str
    prompt_level: str
    latency_ms: int | None
    at: dt.datetime


@dataclass(frozen=True, slots=True)
class MasteryChange:
    skill_code: str
    skill_label_ar: str
    from_state: str
    to_state: str


@dataclass(frozen=True, slots=True)
class SessionFacts:
    activities_completed: int
    correct: int
    incorrect: int
    no_response: int
    independent_responses: int
    supported_responses: int
    skills_practised: tuple[str, ...]
    skill_labels_ar: tuple[str, ...]
    activity_types: tuple[str, ...]
    mastery_changes: tuple[MasteryChange, ...]
    stars_earned: int
    achievements_unlocked: tuple[str, ...]
    duration_minutes: int
    best_streak: int
    #: Skills where the child was right every time, and skills where they were
    #: not. The caregiver report's two lists.
    went_well: tuple[str, ...] = ()
    needs_practice: tuple[str, ...] = ()
    median_latency_ms: int | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "activities_completed": self.activities_completed,
            "correct": self.correct,
            "incorrect": self.incorrect,
            "no_response": self.no_response,
            "independent_responses": self.independent_responses,
            "supported_responses": self.supported_responses,
            "skills_practised": list(self.skills_practised),
            "skill_labels_ar": list(self.skill_labels_ar),
            "activity_types": list(self.activity_types),
            "mastery_changes": [
                {
                    "skill_code": change.skill_code,
                    "skill_label_ar": change.skill_label_ar,
                    "from_state": change.from_state,
                    "to_state": change.to_state,
                }
                for change in self.mastery_changes
            ],
            "stars_earned": self.stars_earned,
            "achievements_unlocked": list(self.achievements_unlocked),
            "duration_minutes": self.duration_minutes,
            "best_streak": self.best_streak,
            "went_well": list(self.went_well),
            "needs_practice": list(self.needs_practice),
            "median_latency_ms": self.median_latency_ms,
        }


def best_streak(attempts: Sequence[AttemptFact]) -> int:
    """The longest run of consecutive successes, in the order they happened."""
    best = running = 0
    for attempt in attempts:
        running = running + 1 if attempt.result in REWARDED_RESULTS else 0
        best = max(best, running)
    return best


def compute(
    attempts: Sequence[AttemptFact],
    *,
    mastery_changes: Sequence[MasteryChange] = (),
    stars_earned: int = 0,
    achievements_unlocked: Sequence[str] = (),
    duration_minutes: int = 0,
) -> SessionFacts:
    """Every number the caregiver report and the child's closing screen use."""
    correct = sum(1 for a in attempts if a.result in REWARDED_RESULTS)
    no_response = sum(1 for a in attempts if a.result == "no_response")
    incorrect = len(attempts) - correct - no_response

    independent = sum(
        1 for a in attempts if a.prompt_level in INDEPENDENT_LEVELS and a.result in REWARDED_RESULTS
    )
    supported = correct - independent

    # Insertion-ordered, so the report lists skills in the order the child met
    # them rather than alphabetically, which is how a caregiver remembers the
    # session.
    skills: dict[str, str] = {}
    for attempt in attempts:
        skills.setdefault(attempt.skill_code, attempt.skill_label_ar)

    per_skill: dict[str, list[bool]] = {}
    for attempt in attempts:
        per_skill.setdefault(attempt.skill_code, []).append(attempt.result in REWARDED_RESULTS)
    went_well = tuple(skills[code] for code, results in per_skill.items() if all(results))
    needs_practice = tuple(skills[code] for code, results in per_skill.items() if not all(results))

    latencies = sorted(a.latency_ms for a in attempts if a.latency_ms is not None)
    median = latencies[len(latencies) // 2] if latencies else None

    types: list[str] = []
    for attempt in attempts:
        if attempt.activity_type not in types:
            types.append(attempt.activity_type)

    return SessionFacts(
        activities_completed=len(attempts),
        correct=correct,
        incorrect=incorrect,
        no_response=no_response,
        independent_responses=independent,
        supported_responses=supported,
        skills_practised=tuple(skills),
        skill_labels_ar=tuple(skills.values()),
        activity_types=tuple(types),
        mastery_changes=tuple(mastery_changes),
        stars_earned=stars_earned,
        achievements_unlocked=tuple(achievements_unlocked),
        duration_minutes=duration_minutes,
        best_streak=best_streak(attempts),
        went_well=went_well,
        needs_practice=needs_practice,
        median_latency_ms=median,
    )


#: The caregiver-facing fallback narrative. PLACEHOLDER Arabic, agent-written.
#: → REVIEW-QUEUE.md #6
TEMPLATE_AR = (
    "لعبنا {activities} ألعاب مع بعض النهارده.\n"
    "{independent} مرة جاوب لوحده.\n"
    "شغل حلو، وكمّلنا لآخر اللعبة.\n"
    "نكمل بكرة من نفس المكان."
)


def template_narrative(facts: SessionFacts) -> str:
    return TEMPLATE_AR.format(
        activities=facts.activities_completed,
        independent=facts.independent_responses,
    )


def allowed_numbers(facts: SessionFacts) -> set[str]:
    """Every number a narrative is permitted to contain.

    Deliberately small. A summary that mentions a number this session did not
    produce is a summary that invented a fact about a child.
    """
    return {
        str(facts.activities_completed),
        str(facts.correct),
        str(facts.independent_responses),
        str(facts.supported_responses),
        str(facts.stars_earned),
        str(facts.duration_minutes),
        str(len(facts.skills_practised)),
    }


def narrative_violations(narrative: str, facts: SessionFacts) -> list[str]:
    """Why a generated narrative may not ship. Empty means it may.

    Reuses `guardrails.normalise_number`, so Arabic-Indic digits are compared
    against Western ones rather than passing because they look different.
    """
    import re

    from app.guardrails.layers import normalise_number

    problems: list[str] = []
    lines = [line for line in narrative.strip().splitlines() if line.strip()]
    if not 2 <= len(lines) <= 5:
        problems.append(f"narrative has {len(lines)} lines, must have 2-5")

    allowed = {normalise_number(value) for value in allowed_numbers(facts)}
    for token in re.findall(r"[\d٠-٩]+", narrative):
        if normalise_number(token) not in allowed:
            problems.append(f"contains a number this session did not produce: {token}")
    return problems


def resolve_narrative(
    *, ai_narrative: str | None, facts: SessionFacts
) -> tuple[str, str, list[str]]:
    """(narrative, source, why the model's was rejected).

    `source` is 'ai' or 'template' and is stored, so a console can tell one
    from the other rather than a caregiver being told a template was written
    for them.
    """
    fallback = template_narrative(facts)
    if not ai_narrative:
        return fallback, "template", ["no ai narrative"]
    problems = narrative_violations(ai_narrative, facts)
    if problems:
        return fallback, "template", problems
    return ai_narrative, "ai", []


__all__ = [
    "TEMPLATE_AR",
    "AttemptFact",
    "MasteryChange",
    "SessionFacts",
    "allowed_numbers",
    "best_streak",
    "compute",
    "narrative_violations",
    "resolve_narrative",
    "template_narrative",
]
