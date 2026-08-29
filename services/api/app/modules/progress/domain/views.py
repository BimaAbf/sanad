"""The four caregiver-facing views, and the three product rules inside them.

docs/04a §C09 lists three rules under "Design rules that matter here". They are
implemented here rather than in the client, because a rule that lives in the UI
is a rule the next client forgets:

1. **No trend line before 3 data points.** A two-point "trend" in a
   developmental measure is noise. Showing it to an anxious parent is not a
   presentation flaw; it is telling them something untrue about their child.
2. **No percentile, no age comparison, no DQ on any dashboard.** DQ exists, and
   it belongs inside the report behind the opt-in norm panel, in context, with
   explanation. On a dashboard it is a number with no context, seen daily.
3. **Regression is never a bare negative signal.** If mastered skills fall or a
   domain DA drops, the response carries a `revisit_plan` of exactly three
   activities. "Let's revisit a few things together" — never a red arrow.

Rule 2 is additionally enforced across the *whole* OpenAPI schema by a test, so
a future endpoint cannot reintroduce it somewhere else.

Pure. No I/O.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.modules.progress.domain.rollup import Rollup

#: docs/04a §C09. Below this many points there is no trend, only two numbers.
MIN_POINTS_FOR_TREND = 3

#: docs/04a §C09 — "a specific 3-activity plan". Exactly three: one is not a
#: plan and five is a chore.
REVISIT_ACTIVITIES = 3

INSUFFICIENT_DATA = "insufficient_data"

#: Copy keys, resolved by the client from the i18n bundle. The API never ships
#: caregiver-facing Arabic: it would bypass the banned-terms lint that runs over
#: the bundle, which is the only thing standing between a parent and the word
#: "متأخر".
COPY_INSUFFICIENT_DATA = "progress.journey.insufficient_data"
COPY_REVISIT = "progress.revisit.intro"


@dataclass(frozen=True, slots=True)
class SkillCard:
    skill_id: str
    code: str
    label_ar: str
    category: str
    state: str
    #: Present for the console and the adaptive engine, never rendered as a
    #: percentage to a caregiver.
    p_known: float
    due_at: dt.datetime | None = None
    last_seen_at: dt.datetime | None = None


@dataclass(frozen=True, slots=True)
class AssessmentPoint:
    assessment_id: str
    completed_at: dt.date
    #: domain code → developmental age in months.
    domain_da: dict[str, float]
    skills_mastered: int


@dataclass(frozen=True, slots=True)
class Activity:
    activity_code: str
    skill_id: str
    label_ar: str


@dataclass(frozen=True, slots=True)
class TodayView:
    date: str
    sessions: int
    minutes: int
    attempts: int
    streak_days: int
    #: A copy key plus its parameters, never a rendered sentence.
    suggestion: Activity | None
    #: Non-empty only when something went down. Always exactly 3 when present.
    revisit_plan: tuple[Activity, ...] = ()
    regression_detected: bool = False


@dataclass(frozen=True, slots=True)
class SkillsView:
    total: int
    mastered: int
    practising: int
    not_started: int
    by_category: dict[str, list[SkillCard]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class JourneyView:
    #: Empty when there is not enough history. `status` says which case it is.
    points: tuple[AssessmentPoint, ...]
    status: str
    copy_key: str = ""
    revisit_plan: tuple[Activity, ...] = ()


def streak_days(day_rollups: Sequence[Rollup], *, today: dt.date) -> int:
    """Consecutive days ending today (or yesterday) with at least one session.

    Yesterday counts as still alive: a streak that breaks at 00:00 punishes a
    family for the clock rather than for anything they did, and the first thing
    a streak must not do is become another source of pressure.
    """
    played = {
        dt.date.fromisoformat(rollup.period.removeprefix("day:"))
        for rollup in day_rollups
        if rollup.period.startswith("day:") and rollup.sessions > 0
    }
    if not played:
        return 0

    cursor = today if today in played else today - dt.timedelta(days=1)
    if cursor not in played:
        return 0
    count = 0
    while cursor in played:
        count += 1
        cursor -= dt.timedelta(days=1)
    return count


def detect_regression(
    *, current: Rollup | None, previous: Rollup | None, points: Sequence[AssessmentPoint]
) -> bool:
    """Mastered skills fell, or any domain's developmental age fell.

    Deliberately generous about what counts: a caregiver noticing a drop that
    the product did not acknowledge is worse than the product offering a
    revisit plan that was not strictly needed.
    """
    if (
        current is not None
        and previous is not None
        and current.skills_mastered < previous.skills_mastered
    ):
        return True
    if len(points) >= 2:
        latest, prior = points[-1], points[-2]
        for domain, value in latest.domain_da.items():
            if domain in prior.domain_da and value < prior.domain_da[domain]:
                return True
    return False


def build_revisit_plan(candidates: Sequence[Activity]) -> tuple[Activity, ...]:
    """Exactly three activities, or none at all.

    Returning one or two would be worse than returning zero: it presents a
    regression *and* an inadequate answer to it. If the engine cannot offer
    three, the caller falls back to the ordinary next-activity path and the
    regression is simply not surfaced.
    """
    if len(candidates) < REVISIT_ACTIVITIES:
        return ()
    return tuple(candidates[:REVISIT_ACTIVITIES])


def build_today(
    *,
    today: dt.date,
    day_rollup: Rollup | None,
    previous_day_rollup: Rollup | None,
    history: Sequence[Rollup],
    suggestion: Activity | None,
    revisit_candidates: Sequence[Activity] = (),
    assessment_points: Sequence[AssessmentPoint] = (),
) -> TodayView:
    regressed = detect_regression(
        current=day_rollup, previous=previous_day_rollup, points=assessment_points
    )
    plan = build_revisit_plan(revisit_candidates) if regressed else ()
    return TodayView(
        date=today.isoformat(),
        sessions=day_rollup.sessions if day_rollup else 0,
        minutes=day_rollup.minutes if day_rollup else 0,
        attempts=day_rollup.attempts if day_rollup else 0,
        streak_days=streak_days(history, today=today),
        suggestion=suggestion,
        revisit_plan=plan,
        # Only claimed when there is a plan to go with it. A regression flag on
        # its own is exactly the bare negative signal the rule forbids.
        regression_detected=regressed and bool(plan),
    )


def build_skills(cards: Sequence[SkillCard]) -> SkillsView:
    by_category: dict[str, list[SkillCard]] = {}
    for card in cards:
        by_category.setdefault(card.category, []).append(card)

    mastered = sum(1 for card in cards if card.state in {"mastered", "retained"})
    practising = sum(1 for card in cards if card.state in {"practising", "emerging"})
    return SkillsView(
        total=len(cards),
        mastered=mastered,
        practising=practising,
        not_started=len(cards) - mastered - practising,
        by_category={
            key: sorted(value, key=lambda c: c.code) for key, value in sorted(by_category.items())
        },
    )


def build_journey(
    points: Sequence[AssessmentPoint],
    *,
    revisit_candidates: Sequence[Activity] = (),
) -> JourneyView:
    """The longitudinal view, with rule 1 applied.

    Under three assessments the endpoint returns `insufficient_data` and a copy
    key — not an empty chart, and not two points joined by a line.
    """
    ordered = tuple(sorted(points, key=lambda point: point.completed_at))
    if len(ordered) < MIN_POINTS_FOR_TREND:
        return JourneyView(points=(), status=INSUFFICIENT_DATA, copy_key=COPY_INSUFFICIENT_DATA)

    regressed = detect_regression(current=None, previous=None, points=ordered)
    plan = build_revisit_plan(revisit_candidates) if regressed else ()
    return JourneyView(points=ordered, status="ok", revisit_plan=plan)


#: Field names that must never appear on a dashboard payload. Checked against
#: the generated OpenAPI schema, so a future endpoint cannot slip one through.
FORBIDDEN_DASHBOARD_FIELDS: frozenset[str] = frozenset(
    {
        "dq",
        "developmental_quotient",
        "percentile",
        "centile",
        "z_score",
        "age_equivalent_percentile",
        "norm_comparison",
        "peer_comparison",
        "rank",
    }
)
