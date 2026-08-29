"""The mastery-judge evidence bundle (DP3).

What is INCLUDED and why (docs/04c §C07):
  * choice position — to detect position bias
  * the specific wrong choice — to tell a meaningful confusion from a random tap
  * latency relative to *that child's own* baseline; absolute latency is
    meaningless for this population

What is EXCLUDED and why:
  * the child's name, their age in years, their diagnosis, anything else that
    could bias the judgement toward low expectations.

**The judge does not know the child has Down syndrome.** That is deliberate. The
evidence should speak, and expectation effects are real in models as in people.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

#: Keys that must never appear anywhere in a bundle. Asserted by a test that
#: walks the serialised payload, not merely by convention.
FORBIDDEN_BUNDLE_KEYS: frozenset[str] = frozenset(
    {
        "name",
        "display_name",
        "child_name",
        "age_years",
        "age",
        "date_of_birth",
        "dob",
        "diagnosis",
        "diagnosis_note",
        "condition",
        "syndrome",
        "governorate",
        "comms_level",
    }
)


@dataclass(frozen=True, slots=True)
class EvidenceAttempt:
    day_offset: int
    result: str
    latency_ms: int
    prompt_level: str
    choice_count: int
    position: int
    selected: str | None = None


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    skill_code: str
    modality: str
    deterministic_rule_met: bool
    p_known: float
    attempts: tuple[EvidenceAttempt, ...]
    baseline_latency_ms: int
    distinct_days: int
    delayed_retrieval_days: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_code": self.skill_code,
            "modality": self.modality,
            "deterministic_rule_met": self.deterministic_rule_met,
            "p_known": round(self.p_known, 4),
            "attempts": [
                {
                    "day_offset": a.day_offset,
                    "result": a.result,
                    "latency_ms": a.latency_ms,
                    "prompt_level": a.prompt_level,
                    "choice_count": a.choice_count,
                    "position": a.position,
                    **({"selected": a.selected} if a.selected else {}),
                }
                for a in self.attempts
            ],
            "baseline_latency_ms": self.baseline_latency_ms,
            "distinct_days": self.distinct_days,
            "delayed_retrieval_days": self.delayed_retrieval_days,
        }


@dataclass(frozen=True, slots=True)
class RawAttempt:
    at: dt.datetime
    result: str
    latency_ms: int
    prompt_level: str
    choice_count: int
    position: int
    selected_skill_id: str | None = None


def build_bundle(
    *,
    skill_code: str,
    modality: str,
    deterministic_rule_met: bool,
    p_known: float,
    attempts: Sequence[RawAttempt],
    baseline_latency_ms: int,
    now: dt.datetime,
) -> EvidenceBundle:
    """Assemble one skill's evidence.

    Dates become day offsets relative to `now`, so no absolute timestamp — which
    is quasi-identifying when combined with anything else — crosses the boundary.
    """
    days = {a.at.date() for a in attempts}
    correct = [a for a in attempts if a.result == "correct"]
    delayed = 0
    if correct:
        first = min(a.at for a in correct)
        delayed = max((a.at - first).days for a in correct)

    return EvidenceBundle(
        skill_code=skill_code,
        modality=modality,
        deterministic_rule_met=deterministic_rule_met,
        p_known=p_known,
        attempts=tuple(
            EvidenceAttempt(
                day_offset=-(now.date() - a.at.date()).days,
                result=a.result,
                latency_ms=a.latency_ms,
                prompt_level=a.prompt_level,
                choice_count=a.choice_count,
                position=a.position,
                selected=a.selected_skill_id,
            )
            for a in attempts
        ),
        baseline_latency_ms=baseline_latency_ms,
        distinct_days=len(days),
        delayed_retrieval_days=delayed,
    )


def forbidden_keys_present(payload: Any, path: str = "") -> list[str]:
    """Every forbidden key found anywhere in a bundle. Empty means clean."""
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            lowered = str(key).lower()
            here = f"{path}.{key}" if path else str(key)
            if lowered in FORBIDDEN_BUNDLE_KEYS:
                found.append(here)
            found.extend(forbidden_keys_present(value, here))
    elif isinstance(payload, list | tuple):
        for index, item in enumerate(payload):
            found.extend(forbidden_keys_present(item, f"{path}[{index}]"))
    return found
