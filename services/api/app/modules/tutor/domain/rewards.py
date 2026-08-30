"""The reward rule. Deterministic, pure, and the only thing that grants a star.

A star is earned by an OUTCOME, never by an interaction. Tapping a card is not
worth a star; a correct response is. That distinction is the whole module, and
it is why this takes an evaluated outcome rather than a request.

Every reward carries its own idempotency key, derived from the thing that earned
it — the attempt's key, or the session's id. Two identical keys are one reward,
enforced by a UNIQUE index rather than by remembering to check. A child who
double-taps, a client that retries after a timeout, and an outbox draining after
a dropped connection all produce the same key and therefore the same total.

The achievement codes are a closed set. A code that is not in `ACHIEVEMENTS`
cannot be awarded, because the caregiver-facing Arabic for it would not exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

#: An independent correct answer. The most a single activity can be worth.
STARS_INDEPENDENT_CORRECT = 2

#: A correct answer the child was helped to. Still a success, and still worth
#: something — errorless learning means help is the method, not a penalty — but
#: not worth as much as doing it alone.
STARS_SUPPORTED_CORRECT = 1

#: Finishing the session. Awarded for finishing, not for accuracy: a child who
#: found the whole session hard and stayed to the end has done the thing the
#: product most wants to encourage.
STARS_SESSION_COMPLETE = 3

#: Correct answers in a row inside one session that unlock `five_in_a_row`.
STREAK_FOR_ACHIEVEMENT = 5

#: Distinct days with a completed session that unlock `three_day_streak`.
DAYS_FOR_STREAK_ACHIEVEMENT = 3


class Achievement(StrEnum):
    FIRST_SESSION = "first_session"
    FIVE_IN_A_ROW = "five_in_a_row"
    FIRST_WORD_SPOKEN = "first_word_spoken"
    FIRST_LETTER_TRACED = "first_letter_traced"
    SKILL_MASTERED = "skill_mastered"
    THREE_DAY_STREAK = "three_day_streak"


#: Caregiver-facing Arabic, one line each. PLACEHOLDER — agent-written, not
#: reviewed by a native Egyptian speaker. → REVIEW-QUEUE.md #6
ACHIEVEMENT_LABEL_AR: dict[Achievement, str] = {
    Achievement.FIRST_SESSION: "أول لعبة خلصناها",
    Achievement.FIVE_IN_A_ROW: "خمس مرات صح ورا بعض",
    Achievement.FIRST_WORD_SPOKEN: "أول كلمة قولناها",
    Achievement.FIRST_LETTER_TRACED: "أول حرف كتبناه",
    Achievement.SKILL_MASTERED: "حاجة جديدة عرفناها كويس",
    Achievement.THREE_DAY_STREAK: "تلات أيام ورا بعض",
}

#: Results that count as a success for reward purposes. `incorrect` and
#: `no_response` are absent on purpose: there is no failure state in the child
#: UI, and that is a rule about what a child is SHOWN, not a licence to pay a
#: child for a wrong answer.
REWARDED_RESULTS = frozenset({"correct", "accepted_on_effort", "caregiver_confirmed"})


@dataclass(frozen=True, slots=True)
class RewardGrant:
    """One reward to write. `idempotency_key` is what makes it write once."""

    stars: int
    reason: str
    kind: str
    idempotency_key: str


def stars_for_attempt(*, result: str, prompt_level: str) -> int:
    """How much one evaluated attempt is worth.

    `full_model` is zero however the attempt is recorded: the answer was given
    to the child, and paying for it would make the fastest route to a full
    sticker chart "wait for the prompt ladder to answer for you".
    """
    if result not in REWARDED_RESULTS:
        return 0
    if prompt_level == "full_model":
        return 0
    if prompt_level == "independent" and result == "correct":
        return STARS_INDEPENDENT_CORRECT
    return STARS_SUPPORTED_CORRECT


def attempt_reward(*, result: str, prompt_level: str, attempt_key: str) -> RewardGrant | None:
    """The reward for one attempt, or None when it earned nothing.

    Keyed on the attempt's own idempotency key, so the reward is exactly as
    replayable as the attempt is. A retried POST creates neither a second
    attempt row nor a second star.
    """
    stars = stars_for_attempt(result=result, prompt_level=prompt_level)
    if stars == 0:
        return None
    return RewardGrant(
        stars=stars,
        reason=f"{result}:{prompt_level}",
        kind="activity",
        idempotency_key=f"attempt:{attempt_key}",
    )


def session_reward(*, session_id: str, activities_done: int) -> RewardGrant | None:
    """The completion bonus. A session with nothing in it did not happen."""
    if activities_done <= 0:
        return None
    return RewardGrant(
        stars=STARS_SESSION_COMPLETE,
        reason="session_complete",
        kind="session_complete",
        idempotency_key=f"session_complete:{session_id}",
    )


@dataclass(frozen=True, slots=True)
class AchievementContext:
    """Everything the achievement rules read. All of it comes from the database."""

    completed_sessions: int = 0
    distinct_session_days: int = 0
    best_streak_this_session: int = 0
    accepted_speech_attempts: int = 0
    passed_tracings: int = 0
    skills_mastered: int = 0


def achievements_earned(context: AchievementContext) -> tuple[Achievement, ...]:
    """Every achievement the child now qualifies for, in a stable order.

    Returns what is TRUE, not what is new. Deciding what is new is the
    repository's job, because "new" is a fact about the database and this
    function has to stay pure to be worth testing.
    """
    earned: list[Achievement] = []
    if context.completed_sessions >= 1:
        earned.append(Achievement.FIRST_SESSION)
    if context.best_streak_this_session >= STREAK_FOR_ACHIEVEMENT:
        earned.append(Achievement.FIVE_IN_A_ROW)
    if context.accepted_speech_attempts >= 1:
        earned.append(Achievement.FIRST_WORD_SPOKEN)
    if context.passed_tracings >= 1:
        earned.append(Achievement.FIRST_LETTER_TRACED)
    if context.skills_mastered >= 1:
        earned.append(Achievement.SKILL_MASTERED)
    if context.distinct_session_days >= DAYS_FOR_STREAK_ACHIEVEMENT:
        earned.append(Achievement.THREE_DAY_STREAK)
    return tuple(earned)


__all__ = [
    "ACHIEVEMENT_LABEL_AR",
    "DAYS_FOR_STREAK_ACHIEVEMENT",
    "REWARDED_RESULTS",
    "STARS_INDEPENDENT_CORRECT",
    "STARS_SESSION_COMPLETE",
    "STARS_SUPPORTED_CORRECT",
    "STREAK_FOR_ACHIEVEMENT",
    "Achievement",
    "AchievementContext",
    "RewardGrant",
    "achievements_earned",
    "attempt_reward",
    "session_reward",
    "stars_for_attempt",
]
