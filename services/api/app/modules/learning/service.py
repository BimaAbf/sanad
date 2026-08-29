"""The mastery loop: attempts in, `skill_states` and `mastery_events` out.

This is the connection that was missing. Attempts have been stored since the
play module existed, and `skill_states` was read by four modules and written by
none -- so a child could play forever and `p_known` never moved, no skill ever
left `not_started`, and nothing could reach `mastered`. Every piece needed to
close it was already built and tested; none of them was called by anything.

**It runs P08's orchestrator rather than a second copy of the rules.**
`tutor_ai/session.py` already folds BKT over attempts, tracks distinct days and
delayed passes, applies `mastery_rule`, clamps an AI verdict through
`enforce_conservatism` and decides the transition -- with 67 tests and 100%
branch coverage. Re-deriving any of that here would create two implementations
of the one rule in the product where being wrong is silent and lands in a
child's clinical record. So this module loads state, hands it to `session.py`,
and writes back what comes out. `tutor_ai` stops being unreachable code as a
consequence, which was the other half of the same problem.

**The fold restarts from the prior on every run; the mastery ladder does not.**
Two different kinds of quantity need two different treatments:

* `p_known` is a *function of the attempts*. Recomputed from `BktState()` over
  the whole history each time, so it is idempotent: a replayed outbox or a
  retried request cannot move it. An incremental update would make a clinical
  number depend on how many times the code happened to run.
* `state` is a *history of decisions*. Seeded from the stored value, because
  `next_state` advances one rung per evaluation by design (`not_started` ->
  `introduced` -> `practising`), and a from-scratch replay would collapse a
  child's whole journey into a single step every time.

**Mastery is still only ever granted by the deterministic rule.** No AI verdict
reaches this path -- `judge_and_commit` is called with none -- and the
`ai_cannot_grant` CHECK on `mastery_events` is the database's own backstop
against a future caller that passes one.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import structlog

from app.modules.learning.domain import scheduling
from app.modules.learning.domain.bkt import BktState, PromptLevel, apply_decay
from app.modules.learning.domain.mastery import LAPSE_THRESHOLD, MasteryState
from app.modules.learning.domain.snapshot import AttemptFact, is_correct, summarise
from app.modules.learning.repository import LearningRepository
from app.modules.tutor_ai.session import (
    IngestedAttempt,
    SkillProgress,
    ingest,
    judge_and_commit,
    start_session,
)

logger = structlog.get_logger(__name__)

#: A latency the client never reported cannot say how quickly the child
#: answered, so it must not be allowed to *look* fast. A ratio of 1.0 is exactly
#: the child's own configured wait time, which `quality_from_latency` scores 3 --
#: the neutral rung. Defaulting to 0 would score every silent client a 5 and
#: stretch review intervals on evidence that does not exist.
NEUTRAL_LATENCY_RATIO = 1.0

#: How many overdue rows one decay sweep will touch. The job is a backstop, not
#: a deadline, and an unbounded UPDATE over every child is the shape of outage
#: that only shows up once the product has users.
DECAY_BATCH = 500


@dataclass(frozen=True, slots=True)
class Transition:
    """One skill that changed state. Returned so callers can react."""

    skill_id: UUID
    modality: str
    from_state: MasteryState
    to_state: MasteryState
    p_known: float
    rule_satisfied: bool


class MasteryService:
    def __init__(self, *, repo: LearningRepository) -> None:
        self._repo = repo

    async def apply_session(
        self,
        *,
        child_id: UUID,
        session_id: UUID,
        wait_time_ms: int,
        now: dt.datetime,
    ) -> list[Transition]:
        """Recompute every skill this session touched. Returns the transitions.

        Safe to call twice for the same session: the attempts are the same, so
        the fold is the same. The mastery ladder does advance a rung on the
        second call, which is a deliberate consequence of seeding `state` from
        the database -- a second `end` on one session is not a normal event, and
        the alternative (never advancing) would need a stored evaluation count
        that docs/02 does not have.
        """
        targets = await self._repo.session_targets(session_id)
        if not targets:
            return []

        skill_ids = sorted({skill_id for skill_id, _ in targets})
        history = await self._repo.load_history(child_id=child_id, skill_ids=skill_ids)
        stored = {
            (row.skill_id, str(row.modality)): row
            for row in await self._repo.load_states(child_id=child_id, skill_ids=skill_ids)
        }

        state = start_session(session_id=str(session_id), candidates=[])
        # Seed the ladder position before ingesting, so `judge_and_commit` moves
        # from where this child actually is rather than from `not_started`.
        #
        # Over the union of this session's targets and every state already
        # stored for these skills, not just the targets: `load_history` returns
        # the skill's attempts in EVERY modality, so a receptive session on a
        # skill that also has expressive history would otherwise re-seed the
        # expressive key at `not_started` and walk that child's state backwards.
        for skill_id, modality in {*targets, *stored}:
            row = stored.get((skill_id, modality))
            state.progress[(str(skill_id), modality)] = SkillProgress(
                bkt=BktState(),
                state=MasteryState(row.state) if row is not None else MasteryState.NOT_STARTED,
            )

        facts: dict[tuple[str, str], list[AttemptFact]] = {}
        for row in history:
            key = (str(row.skill_id), str(row.modality))
            ingest(
                state,
                IngestedAttempt(
                    idempotency_key=str(row.idempotency_key),
                    skill_id=str(row.skill_id),
                    modality=str(row.modality),
                    result=str(row.result),
                    prompt_level=PromptLevel(str(row.prompt_level)),
                    choice_count=int(row.choice_count),
                    latency_ms=int(row.latency_ms or 0),
                    at=row.client_ts,
                ),
            )
            facts.setdefault(key, []).append(
                AttemptFact(
                    correct=is_correct(str(row.result)),
                    latency_ms=None if row.latency_ms is None else int(row.latency_ms),
                    at=row.client_ts,
                )
            )

        # Drop the seeded keys that turned out to have no attempts behind them.
        #
        # `judge_and_commit` evaluates everything in `state.progress`, and
        # `next_state` advances one rung whenever the rule is unmet -- including
        # for a skill with an empty history, where the rule is unmet only
        # because there is no evidence. Without this, a stored state in a
        # modality this session never touched (an expressive row, say, while the
        # child played a receptive session) would climb `introduced` ->
        # `practising` on the strength of nothing at all.
        for key in [k for k, progress in state.progress.items() if not progress.records]:
            del state.progress[key]

        transitions: list[Transition] = []
        for (skill_key, modality), to_state, rule_satisfied, _event in judge_and_commit(state):
            skill_id = UUID(skill_key)
            progress = state.progress[(skill_key, modality)]
            row = stored.get((skill_id, modality))
            from_state = MasteryState(row.state) if row is not None else MasteryState.NOT_STARTED
            attempts = facts.get((skill_key, modality), [])

            await self._persist(
                child_id=child_id,
                skill_id=skill_id,
                modality=modality,
                progress=progress,
                attempts=attempts,
                stored=row,
                to_state=to_state,
                wait_time_ms=wait_time_ms,
                now=now,
            )

            if to_state is not from_state:
                await self._repo.record_mastery_event(
                    {
                        "child_id": child_id,
                        "skill_id": skill_id,
                        "modality": modality,
                        "from_state": from_state.value,
                        "to_state": to_state.value,
                        "p_known": round(progress.bkt.p_known, 4),
                        "rule_satisfied": rule_satisfied,
                        # No AI verdict reaches this path. The columns exist for
                        # the tutor orchestrator, which may pass one.
                        "ai_verdict": None,
                        "ai_reason": None,
                        "session_id": session_id,
                    }
                )
                transitions.append(
                    Transition(
                        skill_id=skill_id,
                        modality=modality,
                        from_state=from_state,
                        to_state=to_state,
                        p_known=progress.bkt.p_known,
                        rule_satisfied=rule_satisfied,
                    )
                )

        logger.info(
            "mastery_applied",
            session_id=str(session_id),
            skills=len(targets),
            transitions=len(transitions),
        )
        return transitions

    async def _persist(
        self,
        *,
        child_id: UUID,
        skill_id: UUID,
        modality: str,
        progress: SkillProgress,
        attempts: Sequence[AttemptFact],
        stored: Any | None,
        to_state: MasteryState,
        wait_time_ms: int,
        now: dt.datetime,
    ) -> None:
        counters = summarise(attempts)
        interval = float(stored.interval_days) if stored is not None else 1.0
        ease = float(stored.ease_factor) if stored is not None else scheduling.EASE_DEFAULT

        last = attempts[-1] if attempts else None
        ratio = NEUTRAL_LATENCY_RATIO
        if last is not None and last.latency_ms is not None:
            # `max(..., 1)` because a child record with a zero wait time is a bad
            # row, not a reason to raise inside a session-end write.
            ratio = last.latency_ms / max(wait_time_ms, 1)

        plan = scheduling.schedule(
            interval_days=interval,
            ease_factor=ease,
            correct=last.correct if last is not None else False,
            latency_ratio=ratio,
            now=now,
        )

        await self._repo.upsert_state(
            {
                "child_id": child_id,
                "skill_id": skill_id,
                "modality": modality,
                "state": to_state.value,
                "p_known": round(progress.bkt.p_known, 6),
                "p_guess": round(progress.bkt.p_guess, 4),
                "interval_days": plan.interval_days,
                "ease_factor": round(plan.ease_factor, 2),
                "due_at": plan.due_at,
                "distinct_days": counters.distinct_days,
                "last_delayed_pass_at": progress.last_delayed_pass_at,
                "consecutive_correct": counters.consecutive_correct,
                "total_attempts": counters.total_attempts,
                "total_correct": counters.total_correct,
                "avg_latency_ms": counters.avg_latency_ms,
                "first_seen_at": counters.first_seen_at,
                "now": now,
            }
        )

    async def decay_overdue(self, *, now: dt.datetime, limit: int = DECAY_BATCH) -> int:
        """Forgetting for skills past their review date. Returns rows touched.

        The `bkt_decay` cron job (docs/04a C10, 02:30 Cairo). Decay is the one
        thing that moves `p_known` without an attempt, which is why it is a
        separate sweep rather than part of the recompute: the recompute is a
        function of the attempts and must stay one.

        A decayed skill can LAPSE, and that is the point -- a caregiver whose
        child stopped practising should see that, not a `mastered` badge frozen
        from three months ago. It can never be promoted here: `next_state` is
        not called, and the only upward move written by this method is none.
        """
        rows = await self._repo.overdue_states(now=now, limit=limit)
        touched = 0
        for row in rows:
            overdue = scheduling.days_overdue(row.due_at, now)
            decayed = _decay(
                p_known=float(row.p_known),
                days_overdue=overdue,
                ease_factor=float(row.ease_factor),
            )
            state = _lapsed_or_same(MasteryState(str(row.state)), decayed)
            await self._repo.apply_decay(
                {
                    "child_id": row.child_id,
                    "skill_id": row.skill_id,
                    "modality": str(row.modality),
                    "p_known": decayed,
                    "state": state.value,
                    "now": now,
                }
            )
            touched += 1
        logger.info("bkt_decay_swept", rows=touched)
        return touched


def _decay(*, p_known: float, days_overdue: float, ease_factor: float) -> float:
    return apply_decay(
        BktState(p_known=p_known), days_overdue=days_overdue, ease_factor=ease_factor
    )


def _lapsed_or_same(current: MasteryState, p_known: float) -> MasteryState:
    """Only `mastered` and `retained` can lapse.

    Mirrors the first branch of `mastery.next_state`. A `practising` skill whose
    estimate has decayed is still practising -- there is no lower rung for it to
    fall to, and inventing one would put a state on a caregiver's screen that
    docs/02's enum does not have.
    """
    if current in (MasteryState.MASTERED, MasteryState.RETAINED) and p_known < LAPSE_THRESHOLD:
        return MasteryState.LAPSED
    return current


__all__ = ["DECAY_BATCH", "MasteryService", "Transition"]
