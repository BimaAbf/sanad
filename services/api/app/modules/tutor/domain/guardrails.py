"""The deterministic guardrails a teaching decision must pass, in full.

`tutor_ai/brain.py::guard_decision` already checks four things and is at 100%
branch coverage; this runs after it and covers the rest of the list the
specification names, in one place, with one report.

The design rule is REPAIR, NOT REJECT, wherever a repair is obviously right:
a decision that asks for an activity type this skill cannot be taught with
becomes a selection activity, and the session continues. Rejection — falling all
the way back to the deterministic decision — is reserved for the cases where
repairing would mean inventing a teaching intent the model did not express.

Every action taken is named and returned. They are persisted on the decision row
and shown in the AI inspector, so "the model asked for X and we did Y instead"
is visible rather than silently absorbed.

Nothing here can grant mastery, because `BrainDecision` has no mastery field to
carry it. That is structural rather than checked, and there is a test asserting
the schema stays that way.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from app.modules.tutor.domain.contract import (
    NEEDS_DRAWING_SURFACE,
    NEEDS_MICROPHONE,
    SAFE_DEFAULT,
    ActivityType,
    supports,
)
from app.modules.tutor_ai.brain import (
    MAX_DIFFICULTY_JUMP,
    BrainDecision,
    SupportLevel,
)

#: The most activities one session may deliver, whatever the model asks for.
#: docs/04e's session is short by design; a model that keeps saying "one more"
#: is how a short session becomes a long one.
MAX_ACTIVITIES_PER_SESSION = 14

#: The most times the same skill may be repeated back to back before the
#: guardrail insists on something else. Three identical activities in a row is
#: the point at which repetition stops being practice.
MAX_CONSECUTIVE_SAME_SKILL = 3


@dataclass(frozen=True, slots=True)
class GuardContext:
    """Everything the guardrails check against. All of it is server-side truth."""

    #: skill code -> category, for every candidate.
    categories: Mapping[str, str] = field(default_factory=dict)
    #: skill code -> its prerequisites' skill codes.
    prerequisites: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    #: Skills this child has actually mastered or retained.
    mastered: frozenset[str] = frozenset()
    #: The difficulty of the previous activity in this session, if any.
    previous_difficulty: int | None = None
    #: The skill codes of the previous activities, most recent last.
    recent_skills: tuple[str, ...] = ()
    #: How many activities this session has already delivered.
    activities_done: int = 0
    #: Consent and capability. A microphone activity without `voice_asr` and
    #: without a caregiver present is an activity the child cannot complete.
    microphone_allowed: bool = True
    drawing_allowed: bool = True
    #: Skills that have a tracing reference path.
    traceable: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class GuardedActivity:
    activity_type: ActivityType
    difficulty: int
    support_level: str
    repeat: bool
    actions: tuple[str, ...]
    #: True when the session must stop rather than deliver this.
    session_exhausted: bool = False


class SessionLimitReachedError(Exception):
    """The session has delivered everything it is allowed to."""


def enforce(decision: BrainDecision, context: GuardContext) -> GuardedActivity:
    """Every remaining rule from the specification's guardrail list.

    Returns the activity parameters that will actually be delivered, plus the
    name of every repair made on the way there.
    """
    actions: list[str] = []

    if context.activities_done >= MAX_ACTIVITIES_PER_SESSION:
        return GuardedActivity(
            activity_type=SAFE_DEFAULT,
            difficulty=1,
            support_level=str(decision.support_level),
            repeat=False,
            actions=("session_limit_reached",),
            session_exhausted=True,
        )

    # --- prerequisites -----------------------------------------------------
    #
    # The candidate generator already filters on prerequisites, so reaching
    # here means the model named a skill the generator allowed but whose
    # prerequisites have since changed, or a caller assembled the context by
    # hand. Either way the check is cheap and the failure is a child being
    # taught something they have no foundation for.
    missing = tuple(
        prerequisite
        for prerequisite in context.prerequisites.get(decision.next_skill, ())
        if prerequisite not in context.mastered
    )
    if missing:
        raise SessionLimitReachedError(
            f"{decision.next_skill} has unmet prerequisites: {', '.join(missing)}"
        )

    # --- activity type -----------------------------------------------------
    activity_type = _coerce_type(decision.activity_type, actions)
    category = context.categories.get(decision.next_skill, "")

    if category and not supports(activity_type, category):
        actions.append("activity_type_unsupported_for_category")
        activity_type = SAFE_DEFAULT
    if activity_type in NEEDS_MICROPHONE and not context.microphone_allowed:
        # Not an error and not a refusal: the child gets the same skill taught
        # a way their device and their consents allow.
        actions.append("microphone_unavailable")
        activity_type = SAFE_DEFAULT
    if activity_type in NEEDS_DRAWING_SURFACE and (
        not context.drawing_allowed or decision.next_skill not in context.traceable
    ):
        actions.append("no_tracing_reference")
        activity_type = SAFE_DEFAULT

    # --- difficulty --------------------------------------------------------
    difficulty = decision.difficulty
    if context.previous_difficulty is not None:
        ceiling = context.previous_difficulty + MAX_DIFFICULTY_JUMP
        floor = context.previous_difficulty - MAX_DIFFICULTY_JUMP
        if difficulty > ceiling:
            # A jump from 1 to 5 is not a teaching decision, it is a model
            # having lost the thread. Move one step, in the direction asked.
            difficulty = ceiling
            actions.append("difficulty_jump_capped")
        elif difficulty < floor:
            difficulty = floor
            actions.append("difficulty_drop_capped")
    difficulty = max(1, min(5, difficulty))

    # --- repetition --------------------------------------------------------
    repeat = decision.repeat
    tail = context.recent_skills[-MAX_CONSECUTIVE_SAME_SKILL:]
    if (
        len(tail) >= MAX_CONSECUTIVE_SAME_SKILL
        and len(set(tail)) == 1
        and tail[0] == decision.next_skill
    ):
        repeat = False
        actions.append("consecutive_repetition_bounded")

    # --- support -----------------------------------------------------------
    support = str(decision.support_level)
    if difficulty >= 4 and decision.support_level is SupportLevel.LOW:
        # The one combination that is internally contradictory: the hardest
        # activity offered with the least help.
        support = str(SupportLevel.MEDIUM)
        actions.append("support_raised_for_difficulty")

    return GuardedActivity(
        activity_type=activity_type,
        difficulty=difficulty,
        support_level=support,
        repeat=repeat,
        actions=tuple(actions),
    )


def _coerce_type(raw: str, actions: list[str]) -> ActivityType:
    try:
        return ActivityType(raw)
    except ValueError:
        actions.append("unknown_activity_type")
        return SAFE_DEFAULT


#: The floor a delivered activity puts under the prompt level the client may
#: report. A demonstration happened; the response after it is not independent.
#: Without this, "demonstrate then test" would be a free route to independent
#: evidence, and the specification is explicit that a full demonstration must
#: not prove independent mastery.
PROMPT_FLOOR_ORDER = ("independent", "gestural", "partial_verbal", "full_model")


def floor_prompt_level(reported: str, *, demonstrate_first: bool, support_level: str) -> str:
    """The prompt level actually recorded, given what the child was shown.

    The client knows which rung of the ladder it was on and is trusted for that,
    because it is the only thing that does. It is NOT trusted to say a response
    was independent when the server had already told it to demonstrate.
    """
    floor = "independent"
    if demonstrate_first:
        floor = "gestural"
    if support_level == "high":
        floor = "partial_verbal"

    order = PROMPT_FLOOR_ORDER
    reported_index = order.index(reported) if reported in order else 0
    return order[max(reported_index, order.index(floor))]


__all__ = [
    "MAX_ACTIVITIES_PER_SESSION",
    "MAX_CONSECUTIVE_SAME_SKILL",
    "GuardContext",
    "GuardedActivity",
    "SessionLimitReachedError",
    "enforce",
    "floor_prompt_level",
]
