"""The tutor runtime loop — the thing the whole demo is about.

    learner state + assessment + BKT + recent attempts + support history
        -> AI BRAIN (or its deterministic twin)
        -> DETERMINISTIC GUARDRAILS
        -> ACTIVITY
        -> CHILD RESPONSE
        -> AUTHORITATIVE EVALUATION      <- here, never in the browser
        -> ATTEMPT PERSISTED
        -> BKT / MASTERY UPDATE
        -> UPDATED LEARNER STATE
        -> AI BRAIN AGAIN

Four properties this module exists to make true, each of which was false before
it existed:

**The loop runs per activity, not per session.** `next_activity` assembles
evidence from the database every time, so a child who fails twice gets a
different third activity than a child who succeeded twice — inside the same
session, from the same starting state.

**Correctness is decided here.** `respond` reads the answer key from the row the
server wrote and calls `domain/evaluate.py`. The client sends what the child
did and renders what it is told. There is no branch in the browser that decides
whether to celebrate.

**Mastery is recomputed after every response.** `MasteryService.apply_session`
is idempotent by construction (it folds BKT over the whole history from the
prior), so calling it per response rather than per session costs a few queries
and buys the thing the demo has to show: adaptation to evidence that was
recorded thirty seconds ago.

**Nothing is reported that was not persisted.** Stars come back as a `SUM` over
`reward_events` read AFTER the insert, not as the number this request meant to
add. If the insert was a duplicate the sum is unchanged, and the response says
so — the client cannot show a star that is not in the database.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import structlog
from seeds.tracing import traceable_skills

from app.ai.gateway import LlmGateway
from app.core.errors import Conflict, NotFound, ValidationProblem
from app.modules.children.repository import ChildrenRepository
from app.modules.identity.domain import Role
from app.modules.identity.service import IdentityService
from app.modules.learning.domain.candidates import Candidate, CandidateKind, SkillSnapshot
from app.modules.learning.domain.candidates import candidates as build_candidates
from app.modules.learning.domain.mastery import MasteryState
from app.modules.learning.service import MasteryService
from app.modules.progress.domain.rollup import SessionFact
from app.modules.progress.service import ProgressService
from app.modules.tutor import brain_call
from app.modules.tutor.domain import build as build_domain
from app.modules.tutor.domain import guardrails as tutor_guardrails
from app.modules.tutor.domain import report as report_domain
from app.modules.tutor.domain import rewards as rewards_domain
from app.modules.tutor.domain.contract import (
    MODALITY_OF,
    NEEDS_DRAWING_SURFACE,
    NEEDS_MICROPHONE,
    TEACHING_MODALITY,
    Activity,
    ActivityType,
    AnswerKey,
    supports,
)
from app.modules.tutor.domain.evaluate import Evaluation, ResponseInvalidError, evaluate
from app.modules.tutor.repository import TutorRepository
from app.modules.tutor_ai.audit import TutorAuditRepository
from app.modules.tutor_ai.brain import BrainDecision, LearnerEvidence, guard_decision

logger = structlog.get_logger(__name__)

#: How many candidates the brain chooses between. More is not better: the
#: candidate rules already encode the clinical composition (at most one new
#: skill, none while three are practising), and a longer list is a longer list
#: for a model to pick badly from.
CANDIDATE_LIMIT = 8

#: How many recent attempts feed the evidence bundle.
EVIDENCE_ATTEMPTS = 20

#: Distractors pulled per activity. Enough for a four-choice activity plus the
#: competing-word list the speech scorer needs.
POOL_SIZE = 8

#: docs/04c §C06: at most one NEW skill per session. Introducing two competing
#: items in one eight-minute session is how you produce interference in this
#: population, and it is a clinical position rather than a product preference.
NEW_SKILLS_PER_SESSION = 1

#: The exception, and it is a real one. A child in their FIRST ever session has
#: no skills at all, so a limit of one would end the session after a single
#: skill — three activities, then a closing scene. The rule exists to stop
#: competing items being introduced alongside things already in flight; with
#: nothing in flight there is nothing to compete with. Three is the number of
#: distinct skills a first session opens with, and every session after it is
#: back to one.
FIRST_SESSION_NEW_SKILLS = 3

#: How many DISTINCT skills one session may work on.
#:
#: Without a cap the session marches: the starting assessment opens twenty-five
#: skills as due, `candidates()` returns the next five each time it is called,
#: and an answered skill drops to the back — so a fourteen-activity session
#: touched fourteen different skills and repeated none of them. That is the
#: opposite of what a short, repetitive session is for, and it is the shape
#: docs/04e describes: a handful of things, several times each.
MAX_SKILLS_PER_SESSION = 4

#: Wall-clock a session may run before `next_activity` starts refusing. The cap
#: is on top of the activity-count cap, because a tablet left face-up on a table
#: hits neither otherwise.
MAX_SESSION_MINUTES = 30


@dataclass(frozen=True, slots=True)
class DeliveredActivity:
    """What the router serialises.

    `presentation` is the stored JSON rather than a rebuilt `Presentation`.
    That is deliberate: the child is looking at the arrangement that was
    written to the row, and rebuilding it from the seed on every read would be
    a second chance for the two to disagree — a card in a different place after
    a reload, under a child's finger, is exactly the failure the seed exists to
    prevent.
    """

    activity_id: UUID
    ordinal: int
    activity_type: str
    skill_code: str
    difficulty: int
    modality: str
    strategy: str
    support_level: str
    choice_count: int
    presentation: dict[str, Any]
    decision_id: UUID | None
    model_name: str
    used_ai: bool
    wait_time_ms: int
    reason_codes: tuple[str, ...] = ()
    guardrail_actions: tuple[str, ...] = ()
    session_finished: bool = False


@dataclass(frozen=True, slots=True)
class ResponseResult:
    activity_id: UUID
    evaluation: Evaluation
    duplicate: bool
    reward_delta: int
    stars_total: int
    achievements_unlocked: tuple[str, ...]
    mastery_before: float | None
    mastery_after: float | None
    mastery_state: str


class TutorService:
    def __init__(
        self,
        *,
        repo: TutorRepository,
        children: ChildrenRepository,
        identity: IdentityService,
        mastery: MasteryService,
        progress: ProgressService,
        audit: TutorAuditRepository,
        gateway: LlmGateway,
    ) -> None:
        self._repo = repo
        self._children = children
        self._identity = identity
        self._mastery = mastery
        self._progress = progress
        self._audit = audit
        self._gateway = gateway

    # --- sessions ----------------------------------------------------------

    async def start(self, *, child_id: UUID, caregiver_id: UUID) -> Any:
        await self._identity.assert_child_access(
            caregiver_id=caregiver_id, child_id=child_id, min_role=Role.CO_CAREGIVER
        )
        child = await self._child_or_404(child_id)
        # `deterministic_fallback` and not a new value naming the loop: see the
        # note in migration 0014. There is no up-front plan for `plan_source`
        # to describe, and the source of each individual decision is recorded
        # on its own `ai_decisions` row.
        row = await self._repo.create_session(
            child_id=child_id, started_by=caregiver_id, plan_source="deterministic_fallback"
        )
        logger.info("tutor_session_started", session_id=str(row.id), child_id=str(child_id))
        return row, child

    # --- the loop ----------------------------------------------------------

    async def next_activity(self, *, session_id: UUID, caregiver_id: UUID) -> DeliveredActivity:
        """The AI Brain step. Idempotent while an activity is unanswered.

        Re-requesting returns the SAME activity rather than building a new one:
        a reload mid-session must not change what is under the child's finger,
        and a retried request must not consume a decision. The database's
        `tutor_activities_one_pending` index is what guarantees it.
        """
        session = await self._require_session(session_id, caregiver_id)
        if session.ended_at is not None:
            raise Conflict(detail="This session has already finished.")
        child = await self._child_or_404(session.child_id)

        pending = await self._repo.pending_activity(session_id)
        if pending is not None:
            return await self._redeliver(pending, child)

        done = await self._repo.activity_count(session_id)
        elapsed = (_now() - session.started_at).total_seconds() / 60.0
        if done >= tutor_guardrails.MAX_ACTIVITIES_PER_SESSION or elapsed > MAX_SESSION_MINUTES:
            return _finished(done, int(child.wait_time_ms))

        snapshots, rows_by_code, practised = await self._snapshots(session.child_id)
        candidates = await self._candidates(
            session_id=session_id,
            session_child_id=session.child_id,
            session_started_at=session.started_at,
            snapshots=snapshots,
            practised=practised,
        )
        if not candidates:
            if done > 0:
                # The child has worked through everything this session can
                # offer. That is a finished session, not an error, and a
                # closing scene is the correct end to it.
                return _finished(done, int(child.wait_time_ms))
            # Nothing at all, on the first request: an empty catalogue, i.e. a
            # deployment that never ran `sanad seed`.
            raise Conflict(detail="No activities are available for this child yet.")

        context = await self._guard_context(
            child_id=session.child_id,
            session_id=session_id,
            snapshots=snapshots,
            done=done,
        )
        evidence = await self._evidence(
            child_id=session.child_id,
            candidates=candidates,
            session_started_at=session.started_at,
            categories=dict(context.categories),
            microphone_allowed=context.microphone_allowed,
        )

        proposal = await brain_call.propose(
            self._gateway,
            candidates=candidates,
            evidence=evidence,
            child_id=str(session.child_id),
            correlation_id=str(session_id),
        )
        guarded = guard_decision(
            proposal.decision or _deterministic(candidates, evidence),
            candidates,
            evidence,
        )

        try:
            enforced = tutor_guardrails.enforce(guarded.final, context)
        except tutor_guardrails.SessionLimitReachedError:
            # A prerequisite the candidate generator allowed and the guardrail
            # refused. Rather than fail the child's session, drop to the safest
            # candidate the generator produced and record why.
            fallback = _deterministic(candidates, evidence)
            guarded = guard_decision(fallback, candidates, evidence)
            enforced = tutor_guardrails.enforce(guarded.final, context)

        target_row = rows_by_code.get(guarded.final.next_skill)
        if target_row is None:
            raise Conflict(detail="The chosen skill is not in this deployment's catalogue.")

        activity = await self._build(
            decision=guarded.final,
            enforced=enforced,
            target=target_row,
            child=child,
            seed=_seed(session_id, done + 1),
        )

        all_actions = (*guarded.actions, *enforced.actions)
        decision_id = await self._audit.record_decision(
            child_id=session.child_id,
            session_id=session_id,
            state_snapshot=evidence.to_dict(),
            proposed_decision=guarded.proposed.model_dump(mode="json"),
            final_decision=guarded.final.model_dump(mode="json"),
            reason_codes=list(guarded.final.reason_codes),
            guardrail_actions=list(all_actions),
            model_name=proposal.model_name,
            resulting_activity_id=f"{activity.activity_type}:{activity.skill_code}",
        )

        inserted = await self._repo.insert_activity(
            {
                "session_id": session_id,
                "child_id": session.child_id,
                "decision_id": decision_id,
                "ordinal": done + 1,
                "activity_type": str(activity.activity_type),
                "skill_id": target_row.skill_id,
                "skill_code": activity.skill_code,
                "difficulty": activity.difficulty,
                "modality": activity.modality,
                "strategy": activity.strategy,
                "support_level": activity.support_level,
                "prompt_level": activity.prompt_level,
                "choice_count": activity.choice_count,
                "presentation": activity.presentation.as_json(),
                "answer_key": activity.answer_key.as_json(),
            }
        )
        logger.info(
            "tutor_activity_delivered",
            session_id=str(session_id),
            ordinal=int(inserted.ordinal),
            model=proposal.model_name,
            guardrails=len(all_actions),
        )
        return DeliveredActivity(
            activity_id=inserted.id,
            ordinal=int(inserted.ordinal),
            activity_type=str(activity.activity_type),
            skill_code=activity.skill_code,
            difficulty=activity.difficulty,
            modality=activity.modality,
            strategy=activity.strategy,
            support_level=activity.support_level,
            choice_count=activity.choice_count,
            presentation=activity.presentation.as_json(),
            decision_id=decision_id,
            model_name=proposal.model_name,
            used_ai=proposal.used_ai,
            wait_time_ms=int(child.wait_time_ms),
            reason_codes=tuple(guarded.final.reason_codes),
            guardrail_actions=tuple(all_actions),
        )

    async def respond(
        self,
        *,
        session_id: UUID,
        caregiver_id: UUID,
        activity_id: UUID,
        response: dict[str, Any],
        idempotency_key: str,
        latency_ms: int | None,
        reported_prompt_level: str,
    ) -> ResponseResult:
        """Evaluate one response. The only place a response becomes a result."""
        session = await self._require_session(session_id, caregiver_id)
        row = await self._repo.activity(activity_id)
        if row is None or row.session_id != session_id:
            raise NotFound(detail="Activity not found.")

        answer_key = AnswerKey.from_json(dict(row.answer_key))
        activity_type = ActivityType(str(row.activity_type))
        try:
            evaluation = evaluate(
                activity_type=activity_type,
                answer_key=answer_key,
                presentation=dict(row.presentation),
                response=response,
                attempt_no=1,
            )
        except ResponseInvalidError as invalid:
            # A malformed response is a client defect and must NOT be recorded
            # as a wrong answer against the child. 422 rather than a stored
            # `incorrect`.
            raise ValidationProblem(detail=str(invalid)) from invalid

        # The prompt level the client reports is floored by what the server
        # already told it to show. A demonstrated activity cannot come back as
        # independent evidence.
        prompt_level = tutor_guardrails.floor_prompt_level(
            reported_prompt_level,
            demonstrate_first=bool(dict(row.presentation).get("demonstration_ar")),
            support_level=str(row.support_level),
        )

        before = await self._repo.skill_state(
            child_id=session.child_id, skill_id=row.skill_id, modality=str(row.modality)
        )
        p_before = float(before.p_known) if before is not None else None

        selected_skill_id = await self._selected_skill_id(evaluation)
        activity_code = f"{row.activity_type}:{row.skill_code}"
        written = await self._repo.record_attempt(
            {
                "session_id": session_id,
                "child_id": session.child_id,
                "activity_code": activity_code,
                "skill_id": row.skill_id,
                "modality": str(row.modality),
                "result": evaluation.attempt_result,
                "prompt_level": prompt_level,
                "latency_ms": latency_ms,
                "choice_count": int(row.choice_count),
                "selected_skill_id": selected_skill_id,
                "client_ts": _now(),
                "idempotency_key": idempotency_key,
            }
        )

        if written:
            await self._repo.mark_answered(activity_id=activity_id, now=_now())
            # The mastery fold, per response. Idempotent, so a duplicate that
            # got this far would change nothing -- but it is skipped anyway, so
            # a retry does not pay for it.
            child = await self._child_or_404(session.child_id)
            await self._mastery.apply_session(
                child_id=session.child_id,
                session_id=session_id,
                wait_time_ms=int(child.wait_time_ms),
                now=_now(),
                # ONLY the skill this response was about. See the docstring on
                # `apply_session`: without this every earlier skill in the
                # session climbs a rung on every later answer.
                only=(row.skill_id, str(row.modality)),
            )

        after = await self._repo.skill_state(
            child_id=session.child_id, skill_id=row.skill_id, modality=str(row.modality)
        )
        p_after = float(after.p_known) if after is not None else None
        state_after = str(after.state) if after is not None else MasteryState.NOT_STARTED.value

        if written:
            await self._repo.record_outcome(
                {
                    "child_id": session.child_id,
                    "session_id": session_id,
                    "activity_code": activity_code,
                    "skill_id": row.skill_id,
                    "difficulty": int(row.difficulty),
                    "modality": str(row.modality),
                    "strategy": str(row.strategy),
                    "character": _character(row),
                    "expected_answer": answer_key.option_id or answer_key.target_label_ar or "",
                    "learner_response": _response_digest(response),
                    "correctness": evaluation.correct,
                    "similarity": evaluation.score,
                    "response_time_ms": latency_ms,
                    "prompt_level": prompt_level,
                    "mastery_before": p_before,
                    "mastery_after": p_after,
                    "decision_id": row.decision_id,
                    "metrics": evaluation.detail,
                    "threshold": evaluation.threshold,
                    "activity_row_id": activity_id,
                }
            )

        # --- rewards, after the attempt is on file and only if it is new -----
        delta = 0
        if written:
            grant = rewards_domain.attempt_reward(
                result=evaluation.attempt_result,
                prompt_level=prompt_level,
                attempt_key=idempotency_key,
            )
            if grant is not None and await self._repo.grant_reward(
                {
                    "child_id": session.child_id,
                    "session_id": session_id,
                    "activity_id": activity_id,
                    "kind": grant.kind,
                    "stars": grant.stars,
                    "reason": grant.reason,
                    "idempotency_key": grant.idempotency_key,
                }
            ):
                delta = grant.stars

        unlocked = await self._sync_achievements(child_id=session.child_id, session_id=session_id)
        # Read back, never computed forward. If the insert was a duplicate this
        # is the same number as before and the client shows no new star.
        total = await self._repo.total_stars(session.child_id)

        logger.info(
            "tutor_response_evaluated",
            session_id=str(session_id),
            outcome=evaluation.outcome.value,
            duplicate=not written,
            stars=delta,
        )
        return ResponseResult(
            activity_id=activity_id,
            evaluation=evaluation,
            duplicate=not written,
            reward_delta=delta,
            stars_total=total,
            achievements_unlocked=unlocked,
            mastery_before=p_before,
            mastery_after=p_after,
            mastery_state=state_after,
        )

    # --- ending ------------------------------------------------------------

    async def end(
        self, *, session_id: UUID, caregiver_id: UUID, reason: str, minutes: int
    ) -> dict[str, Any]:
        """Close the session, compute the facts, persist everything, report."""
        session = await self._require_session(session_id, caregiver_id)
        now = _now()

        ended = await self._repo.end_session(session_id=session_id, reason=reason, now=now)
        if ended is None:
            raise NotFound(detail="Session not found.")

        attempts = await self._repo.session_attempts(session_id)
        changes = await self._repo.mastery_changes(session_id)

        # The completion bonus, before the facts are computed, so the stars in
        # the report are the stars in the database.
        bonus = rewards_domain.session_reward(
            session_id=str(session_id), activities_done=len(attempts)
        )
        if bonus is not None:
            await self._repo.grant_reward(
                {
                    "child_id": session.child_id,
                    "session_id": session_id,
                    "activity_id": None,
                    "kind": bonus.kind,
                    "stars": bonus.stars,
                    "reason": bonus.reason,
                    "idempotency_key": bonus.idempotency_key,
                }
            )
        unlocked = await self._sync_achievements(child_id=session.child_id, session_id=session_id)

        facts = report_domain.compute(
            [
                report_domain.AttemptFact(
                    skill_code=str(row.skill_code),
                    skill_label_ar=str(row.skill_label_ar),
                    activity_type=str(row.activity_code).split(":")[0],
                    result=str(row.result),
                    prompt_level=str(row.prompt_level),
                    latency_ms=None if row.latency_ms is None else int(row.latency_ms),
                    at=row.client_ts,
                )
                for row in attempts
            ],
            mastery_changes=[
                report_domain.MasteryChange(
                    skill_code=str(row.skill_code),
                    skill_label_ar=str(row.skill_label_ar),
                    from_state=str(row.from_state),
                    to_state=str(row.to_state),
                )
                for row in changes
            ],
            stars_earned=await self._repo.session_stars(session_id),
            achievements_unlocked=list(unlocked),
            duration_minutes=minutes,
        )

        # The narrative comes last and only ever restates the facts above.
        # No model call here today: `resolve_narrative` with no AI narrative is
        # the template, which is the documented AI-OFF behaviour and the one
        # every test exercises.
        narrative, source, _rejections = report_domain.resolve_narrative(
            ai_narrative=None, facts=facts
        )
        await self._repo.save_summary(
            {
                "session_id": session_id,
                "child_id": session.child_id,
                "facts": facts.as_json(),
                "narrative_ar": narrative,
                "narrative_source": source,
            }
        )

        await self._repo.record_session_end_event(
            {
                "child_id": session.child_id,
                "caregiver_id": caregiver_id,
                "props": {
                    "session_id": str(session_id),
                    "minutes": minutes,
                    "attempts": facts.activities_completed,
                    "correct": facts.correct,
                    "by_category": {},
                },
                "client_ts": now,
                "idempotency_key": f"session_end:{session_id}",
            }
        )
        await self._progress.rollup_on_session_end(
            child_id=str(session.child_id),
            session=SessionFact(
                session_id=str(session_id),
                child_id=str(session.child_id),
                started_at=session.started_at,
                minutes=minutes,
                attempts=facts.activities_completed,
                correct=facts.correct,
                by_category={},
            ),
        )

        logger.info(
            "tutor_session_ended",
            session_id=str(session_id),
            activities=facts.activities_completed,
            stars=facts.stars_earned,
        )
        return {
            "session_id": session_id,
            "ended_at": now,
            "facts": facts,
            "narrative_ar": narrative,
            "narrative_source": source,
            "stars_total": await self._repo.total_stars(session.child_id),
        }

    async def report(self, *, session_id: UUID, caregiver_id: UUID) -> dict[str, Any]:
        session = await self._require_session(session_id, caregiver_id)
        row = await self._repo.summary(session_id)
        if row is None:
            raise NotFound(detail="This session has no report yet.")
        return {
            "session_id": session_id,
            "child_id": session.child_id,
            "facts": dict(row.facts),
            "narrative_ar": str(row.narrative_ar),
            "narrative_source": str(row.narrative_source),
            "created_at": row.created_at,
        }

    async def sessions(self, *, child_id: UUID, caregiver_id: UUID) -> list[dict[str, Any]]:
        """A child's session history, newest first.

        This is what "log out, log in, the history is still there" reads. The
        facts come from `session_summaries` when a session produced one and are
        null when it did not — an abandoned session is still a session, and
        showing it with no facts is more honest than hiding it.
        """
        await self._identity.assert_child_access(
            caregiver_id=caregiver_id, child_id=child_id, min_role=Role.CO_CAREGIVER
        )
        return [
            {
                "session_id": row.id,
                "started_at": row.started_at,
                "ended_at": row.ended_at,
                "activities_done": int(row.activities_done),
                "correct_count": int(row.correct_count),
                "stars": int(row.stars),
                "facts": dict(row.facts) if row.facts else None,
                "narrative_ar": str(row.narrative_ar or ""),
                "narrative_source": str(row.narrative_source or ""),
            }
            for row in await self._repo.child_sessions(child_id=child_id)
        ]

    # --- rewards -----------------------------------------------------------

    async def rewards(self, *, child_id: UUID, caregiver_id: UUID) -> dict[str, Any]:
        await self._identity.assert_child_access(
            caregiver_id=caregiver_id, child_id=child_id, min_role=Role.CO_CAREGIVER
        )
        rows = await self._repo.achievements(child_id)
        return {
            "child_id": child_id,
            "stars": await self._repo.total_stars(child_id),
            "achievements": [
                {
                    "code": str(row.code),
                    "label_ar": rewards_domain.ACHIEVEMENT_LABEL_AR.get(
                        rewards_domain.Achievement(str(row.code)), ""
                    ),
                    "awarded_at": row.awarded_at,
                }
                for row in rows
                if str(row.code) in set(rewards_domain.Achievement)
            ],
        }

    # --- the inspector -----------------------------------------------------

    async def inspector(self, *, session_id: UUID, caregiver_id: UUID) -> dict[str, Any]:
        """Real backend rows only. A field with no data says so.

        Every value here is read from `ai_decisions`, `skill_states`,
        `attempts` and `tutor_activities`. Nothing is recomputed for display and
        nothing is invented — an absent number renders as `null` and the panel
        shows "غير متاح" rather than a plausible-looking figure.
        """
        session = await self._require_session(session_id, caregiver_id)
        decisions = await self._repo.decisions(session_id)
        activities = await self._repo.session_activities(session_id)
        attempts = await self._repo.session_attempts(session_id)

        steps: list[dict[str, Any]] = []
        for index, decision in enumerate(decisions):
            final = dict(decision.final_decision)
            proposed = dict(decision.proposed_decision)
            snapshot = dict(decision.state_snapshot)
            steps.append(
                {
                    "decision_id": str(decision.id),
                    "ordinal": index + 1,
                    "created_at": decision.created_at,
                    "model_name": str(decision.model_name),
                    "used_ai": str(decision.model_name) != brain_call.FALLBACK_MODEL,
                    "skill": final.get("next_skill"),
                    "difficulty": final.get("difficulty"),
                    "strategy": final.get("strategy"),
                    "modality": final.get("modality"),
                    "support_level": final.get("support_level"),
                    "activity_type": final.get("activity_type"),
                    "repeat": final.get("repeat"),
                    "reason_codes": list(decision.reason_codes or []),
                    "guardrail_actions": list(decision.guardrail_actions or []),
                    "changed_by_guardrails": proposed != final,
                    "p_known_at_decision": snapshot.get("p_known"),
                    "recent_results": snapshot.get("recent_results", []),
                    "modality_accuracy": snapshot.get("modality_accuracy", {}),
                    "resulting_activity": decision.resulting_activity_id,
                }
            )

        return {
            "session_id": session_id,
            "child_id": session.child_id,
            # Derived from the decisions rather than read from the session row.
            # A session is "ai" when a model actually answered for at least one
            # activity, which is a fact about what happened rather than about
            # what was configured.
            "plan_source": (
                "ai"
                if any(str(d.model_name) != brain_call.FALLBACK_MODEL for d in decisions)
                else brain_call.FALLBACK_MODEL
            ),
            "decisions": steps,
            "activities": [
                {
                    "ordinal": int(row.ordinal),
                    "activity_type": str(row.activity_type),
                    "skill_code": str(row.skill_code),
                    "skill_label_ar": str(row.skill_label_ar),
                    "difficulty": int(row.difficulty),
                    "strategy": str(row.strategy),
                    "support_level": str(row.support_level),
                    "state": str(row.state),
                }
                for row in activities
            ],
            "attempts": [
                {
                    "skill_code": str(row.skill_code),
                    "result": str(row.result),
                    "prompt_level": str(row.prompt_level),
                    "latency_ms": None if row.latency_ms is None else int(row.latency_ms),
                }
                for row in attempts
            ],
        }

    # --- internals ---------------------------------------------------------

    async def _redeliver(self, row: Any, child: Any) -> DeliveredActivity:
        """Hand back the activity already on screen. No new decision, no new row.

        The reason codes and guardrail actions are left empty rather than
        re-derived: they belong to the decision that produced this activity and
        are already on the `ai_decisions` row the inspector reads. Making them
        up here would put two differently-derived explanations of one activity
        into the product.
        """
        return DeliveredActivity(
            activity_id=row.id,
            ordinal=int(row.ordinal),
            activity_type=str(row.activity_type),
            skill_code=str(row.skill_code),
            difficulty=int(row.difficulty),
            modality=str(row.modality),
            strategy=str(row.strategy),
            support_level=str(row.support_level),
            choice_count=int(row.choice_count),
            presentation=dict(row.presentation),
            decision_id=row.decision_id,
            model_name="",
            used_ai=False,
            wait_time_ms=int(child.wait_time_ms),
        )

    async def _candidates(
        self,
        *,
        session_id: UUID,
        session_child_id: UUID,
        session_started_at: dt.datetime,
        snapshots: list[SkillSnapshot],
        practised: frozenset[str],
    ) -> list[Candidate]:
        """What the brain may choose between, for THIS activity.

        `learning/domain/candidates.py` answers a different question — "what
        should this child work on today" — and it answers it well: at most one
        new skill, none while three are practising, lapsed first, ending on a
        win. Run unchanged inside a session it produces a new skill every time
        and then, three skills in, nothing at all: every skill it introduced is
        `practising` with a review date tomorrow, so it is neither due nor
        eligible, and a four-minute session hits an empty candidate set.

        A session needs the second question answered too — "what is this child
        working on RIGHT NOW" — so the skills already delivered in this session
        are candidates regardless of their review date, ordered so that:

          1. an unfinished skill (last answered wrong, or not yet right) leads,
             because the errorless-learning response to a mistake is another go
             at the same thing with more help;
          2. the day's plan follows;
          3. a skill already answered correctly this session comes last, as a
             `confidence` item, so the session can end on a win.

        The brain then chooses between them, and `decision.repeat` finally means
        something. It may reorder; it may not add.
        """
        base = build_candidates(snapshots, now=_now(), limit=CANDIDATE_LIMIT)
        # A skill this child has actually attempted comes before one the
        # starting assessment merely opened.
        #
        # `candidates()` breaks a tie on `due_at` with `intro_order`, and after
        # an assessment EVERY seeded skill shares one `due_at` — so the tie is
        # always broken by curriculum position, and a child whose real work is
        # on letters (intro order 30+) was offered colours (0-9) forever. Real
        # evidence is better evidence than a form, and this is where the tutor
        # says so; the domain rule underneath is unchanged.
        base = sorted(base, key=lambda candidate: candidate.skill_id not in practised)
        modality = {snapshot.skill_id: snapshot.modality for snapshot in snapshots}

        # The new-skill budget. `candidates()` returns at most one NEW item per
        # CALL, which inside a session means one per ACTIVITY -- so a six-
        # activity session with a fresh child introduced six skills, and the
        # clinical rule it was built to honour was silently inverted by being
        # run in a loop.
        before, during = await self._repo.skills_started(
            child_id=session_child_id, since=session_started_at
        )
        budget = FIRST_SESSION_NEW_SKILLS if before == 0 else NEW_SKILLS_PER_SESSION
        if during >= budget:
            base = [c for c in base if c.kind is not CandidateKind.NEW]

        delivered = await self._repo.session_activities(session_id)
        attempts = await self._repo.session_attempts(session_id)
        outcome_by_skill: dict[str, bool] = {}
        for attempt in attempts:
            outcome_by_skill[str(attempt.skill_code)] = (
                str(attempt.result) in rewards_domain.REWARDED_RESULTS
            )

        unfinished: list[Candidate] = []
        settled: list[Candidate] = []
        seen: set[str] = set()
        # Walked newest-first so the dedupe keeps each skill's MOST RECENT
        # delivery, then reversed so the least recently practised comes first.
        # Without the reversal the session locks onto one skill: the fallback
        # takes the head of the list, the head never changes, and a fourteen-
        # activity session became fourteen goes at the same card.
        for row in reversed(delivered):
            code = str(row.skill_code)
            if code in seen:
                continue
            seen.add(code)
            done_well = outcome_by_skill.get(code, False)
            candidate = Candidate(
                skill_id=code,
                modality=modality.get(code, "receptive"),
                kind=CandidateKind.CONFIDENCE if done_well else CandidateKind.DUE,
                priority=len(seen),
            )
            (settled if done_well else unfinished).append(candidate)
        unfinished.reverse()
        settled.reverse()

        # A skill already in flight this session is placed by the two lists
        # above, never by the day's plan — otherwise it appears twice and the
        # plan's ordering wins, which is what pinned the session to one card.
        base = [candidate for candidate in base if candidate.skill_id not in seen]

        # Once enough skills are in flight, the session works on those and takes
        # no more from the day's plan.
        if len(seen) >= MAX_SKILLS_PER_SESSION:
            base = []

        ordered: list[Candidate] = []
        placed: set[str] = set()
        for candidate in (*unfinished, *base, *settled):
            if candidate.skill_id in placed:
                continue
            placed.add(candidate.skill_id)
            ordered.append(candidate)
        return ordered[:CANDIDATE_LIMIT]

    async def _snapshots(
        self, child_id: UUID
    ) -> tuple[list[SkillSnapshot], dict[str, build_domain.SkillRow], frozenset[str]]:
        """The catalogue, this child's state over it, and what they have done.

        The third value is the set of skills with at least one recorded
        attempt — as distinct from the ones a starting assessment opened, which
        have a state and a prior and no evidence at all.
        """
        rows = await self._repo.snapshots(child_id)
        snapshots: list[SkillSnapshot] = []
        by_code: dict[str, build_domain.SkillRow] = {}
        practised: set[str] = set()
        for row in rows:
            code = str(row.code)
            if int(row.total_attempts or 0) > 0:
                practised.add(code)
            by_code[code] = build_domain.SkillRow(
                skill_id=row.skill_id,
                code=code,
                category=str(row.category),
                label_ar=str(row.label_ar),
                label_egy=str(row.label_egy or row.label_ar),
                alt_text_ar=str(row.alt_text_ar),
                intro_order=int(row.intro_order),
            )
            snapshots.append(
                SkillSnapshot(
                    skill_id=code,
                    modality=str(row.modality or "receptive"),
                    state=MasteryState(str(row.state)),
                    due_at=row.due_at,
                    intro_order=int(row.intro_order),
                    difficulty_tier=int(row.difficulty_tier),
                    prerequisites=tuple(row.prerequisites or ()),
                )
            )
        return snapshots, by_code, frozenset(practised)

    def _deliverable(
        self, *, category: str, skill_code: str, microphone_allowed: bool
    ) -> tuple[str, ...]:
        """The activity types that can actually be delivered for this skill.

        Handed to the brain as part of the evidence so it chooses inside the
        set rather than outside it. The guardrail still checks — it is the
        thing that has to hold when a model ignores what it was told — but a
        decision that trips a repair on every single activity carries no
        information about the model, and the repair log stops being readable.
        """
        allowed: list[str] = []
        for activity_type in ActivityType:
            if category and not supports(activity_type, category):
                continue
            if activity_type in NEEDS_MICROPHONE and not microphone_allowed:
                continue
            if activity_type in NEEDS_DRAWING_SURFACE and skill_code not in traceable_skills():
                continue
            allowed.append(str(activity_type))
        return tuple(allowed)

    async def _evidence(
        self,
        *,
        child_id: UUID,
        candidates: list[Candidate],
        session_started_at: dt.datetime,
        categories: dict[str, str],
        microphone_allowed: bool,
    ) -> LearnerEvidence:
        """The bundle the brain reasons over. Every field comes from Postgres."""
        target = candidates[0]
        recent = await self._repo.recent_attempts(child_id=child_id, limit=EVIDENCE_ATTEMPTS)
        # Newest first out of the query; the brain reads them oldest first.
        ordered = list(reversed(recent))
        for_skill = [row for row in ordered if str(row.skill_code) == target.skill_id]
        source = for_skill or ordered

        modality_accuracy = _teaching_modalities(await self._repo.type_accuracy(child_id))
        support = await self._repo.support_effectiveness(child_id)
        profile = await self._repo.profile(child_id)
        recent_types = await self._repo.recent_strategies(child_id)

        state = None
        rows = await self._repo.skills_by_code([target.skill_id])
        if rows:
            state = await self._repo.skill_state(
                child_id=child_id, skill_id=rows[0].id, modality=target.modality
            )

        minutes = int((_now() - session_started_at).total_seconds() // 60)
        return LearnerEvidence(
            skill=target.skill_id,
            modality=target.modality,
            p_known=float(state.p_known) if state is not None else 0.15,
            initial_assessment=(
                float(dict(profile.area_levels or {}).get(_area_of(target.skill_id), 0)) / 3.0
                if profile is not None
                else None
            ),
            recent_results=tuple(str(row.result) for row in source[-8:]),
            prompt_levels=tuple(str(row.prompt_level) for row in source[-8:]),
            response_times_ms=tuple(int(row.latency_ms or 0) for row in source[-8:]),
            modality_accuracy=modality_accuracy,
            demonstration_accuracy=support.get("gestural"),
            speech_accuracy=modality_accuracy.get("expressive"),
            # The teaching strategies this child has actually been given, most
            # recent last. The brain uses them to avoid proposing a fourth
            # identical approach, and `guard_decision` enforces that it does.
            recent_strategies=tuple(recent.strategy for recent in recent_types),
            recent_activity_types=tuple(recent.activity_type for recent in recent_types),
            available_activity_types=self._deliverable(
                category=categories.get(target.skill_id, ""),
                skill_code=target.skill_id,
                microphone_allowed=microphone_allowed,
            ),
            session_minutes=minutes,
            # docs/04e: a session past its comfortable length is a session a
            # child is finishing out of politeness. The profile carries what
            # that length is for this child.
            fatigue=minutes >= (int(profile.comfortable_minutes) if profile is not None else 10),
        )

    async def _guard_context(
        self,
        *,
        child_id: UUID,
        session_id: UUID,
        snapshots: list[SkillSnapshot],
        done: int,
    ) -> tutor_guardrails.GuardContext:
        rows = await self._repo.snapshots(child_id)
        categories = {str(row.code): str(row.category) for row in rows}
        prerequisites = {
            str(row.code): tuple(str(value) for value in (row.prerequisites or [])) for row in rows
        }
        mastered = frozenset(
            snapshot.skill_id
            for snapshot in snapshots
            if snapshot.state in (MasteryState.MASTERED, MasteryState.RETAINED)
        )
        activities = await self._repo.session_activities(session_id)
        consents = await self._repo.consents(child_id)
        return tutor_guardrails.GuardContext(
            categories=categories,
            prerequisites=prerequisites,
            mastered=mastered,
            previous_difficulty=(int(activities[-1].difficulty) if activities else None),
            recent_skills=tuple(str(row.skill_code) for row in activities),
            activities_done=done,
            # A speaking activity needs a microphone the family agreed to. The
            # caregiver-confirm route works without ASR consent, so the check is
            # on `ai_processing` -- the consent that gates any processing at all.
            microphone_allowed=consents.get("ai_processing") == "granted",
            drawing_allowed=True,
            traceable=frozenset(traceable_skills()),
        )

    async def _build(
        self,
        *,
        decision: BrainDecision,
        enforced: tutor_guardrails.GuardedActivity,
        target: build_domain.SkillRow,
        child: Any,
        seed: int,
    ) -> Activity:
        activity_type = enforced.activity_type
        pool = await self._pool(activity_type=activity_type, target=target)
        try:
            return build_domain.build(
                activity_type=activity_type,
                target=target,
                pool=pool,
                difficulty=enforced.difficulty,
                modality=MODALITY_OF[activity_type],
                strategy=str(decision.strategy),
                support_level=enforced.support_level,
                prompt_level="independent",
                demonstrate_first=decision.demonstrate_first,
                max_choices=int(child.max_choices),
                seed=seed,
                caregiver_confirm_allowed=True,
            )
        except ValueError:
            # The builder refused — not enough distractors of the right kind,
            # or a missing reference path the guardrail could not see. Selection
            # always works, so the child gets that instead of an error.
            logger.info("tutor_activity_build_fallback", activity_type=str(activity_type))
            fallback_pool = await self._pool(
                activity_type=ActivityType.SELECT_PICTURE, target=target
            )
            return build_domain.build(
                activity_type=ActivityType.SELECT_PICTURE,
                target=target,
                pool=fallback_pool,
                difficulty=enforced.difficulty,
                modality=MODALITY_OF[ActivityType.SELECT_PICTURE],
                strategy=str(decision.strategy),
                support_level=enforced.support_level,
                prompt_level="independent",
                demonstrate_first=decision.demonstrate_first,
                max_choices=int(child.max_choices),
                seed=seed,
            )

    async def _pool(
        self, *, activity_type: ActivityType, target: build_domain.SkillRow
    ) -> list[build_domain.SkillRow]:
        rows = await self._repo.category_pool(
            category=target.category,
            code=target.code,
            around=target.intro_order,
            limit=POOL_SIZE,
        )
        pool = [
            build_domain.SkillRow(
                skill_id=row.id,
                code=str(row.code),
                category=str(row.category),
                label_ar=str(row.label_ar),
                label_egy=str(row.label_egy or row.label_ar),
                alt_text_ar=str(row.alt_text_ar),
                intro_order=int(row.intro_order),
            )
            for row in rows
        ]
        if activity_type is ActivityType.SORT_CATEGORY:
            others = await self._repo.other_category_pool(category=target.category, limit=3)
            pool.extend(
                build_domain.SkillRow(
                    skill_id=row.id,
                    code=str(row.code),
                    category=str(row.category),
                    label_ar=str(row.label_ar),
                    label_egy=str(row.label_egy or row.label_ar),
                    alt_text_ar=str(row.alt_text_ar),
                    intro_order=int(row.intro_order),
                )
                for row in others
            )
        return pool

    async def _selected_skill_id(self, evaluation: Evaluation) -> UUID | None:
        if not evaluation.selected_skill_code:
            return None
        rows = await self._repo.skills_by_code([evaluation.selected_skill_code])
        return rows[0].id if rows else None

    async def _sync_achievements(self, *, child_id: UUID, session_id: UUID) -> tuple[str, ...]:
        """Award every achievement now true that was not already awarded.

        `grant_achievement` returns whether IT wrote the row, so the unlocked
        list is exactly the ones that became true on this call. A second call
        with the same facts unlocks nothing, which is what stops a caregiver
        being congratulated twice for the same milestone.
        """
        attempts = await self._repo.session_attempts(session_id)
        facts = await self._repo.achievement_context(child_id)
        streak = report_domain.best_streak(
            [
                report_domain.AttemptFact(
                    skill_code=str(row.skill_code),
                    skill_label_ar=str(row.skill_label_ar),
                    activity_type="",
                    result=str(row.result),
                    prompt_level=str(row.prompt_level),
                    latency_ms=None,
                    at=row.client_ts,
                )
                for row in attempts
            ]
        )
        context = rewards_domain.AchievementContext(
            completed_sessions=int(facts.completed_sessions),
            distinct_session_days=int(facts.distinct_days),
            best_streak_this_session=streak,
            accepted_speech_attempts=int(facts.accepted_speech),
            passed_tracings=int(facts.passed_tracings),
            skills_mastered=int(facts.skills_mastered),
        )
        unlocked: list[str] = []
        for achievement in rewards_domain.achievements_earned(context):
            if await self._repo.grant_achievement(
                child_id=child_id, code=str(achievement), session_id=session_id
            ):
                unlocked.append(str(achievement))
        return tuple(unlocked)

    async def _require_session(self, session_id: UUID, caregiver_id: UUID) -> Any:
        session = await self._repo.get_session(session_id)
        if session is None:
            raise NotFound(detail="Session not found.")
        await self._identity.assert_child_access(
            caregiver_id=caregiver_id, child_id=session.child_id, min_role=Role.CO_CAREGIVER
        )
        return session

    async def _child_or_404(self, child_id: UUID) -> Any:
        child = await self._children.get_child(child_id)
        if child is None:
            raise NotFound(detail="Child not found.")
        return child


# --- helpers ---------------------------------------------------------------


def _finished(done: int, wait_time_ms: int) -> DeliveredActivity:
    """The session is over. An explicit state, not an empty activity.

    A client that received a half-built activity here would render a blank
    screen; one that receives `session_finished` shows the closing scene, which
    is the only correct end to a session.
    """
    return DeliveredActivity(
        activity_id=UUID(int=0),
        ordinal=done,
        activity_type="",
        skill_code="",
        difficulty=0,
        modality="",
        strategy="",
        support_level="",
        choice_count=0,
        presentation={},
        decision_id=None,
        model_name=brain_call.FALLBACK_MODEL,
        used_ai=False,
        wait_time_ms=wait_time_ms,
        session_finished=True,
    )


def _deterministic(candidates: list[Candidate], evidence: LearnerEvidence) -> BrainDecision:
    """The decision that ships whenever the model does not answer.

    `guard_decision` builds exactly this internally when it rejects a proposal;
    building it here too means the AI-OFF path runs the SAME code as the
    AI-rejected path, so the fallback cannot rot while the AI path is exercised.
    """
    from app.modules.tutor_ai.brain import _fallback

    return _fallback(candidates, evidence)


def _teaching_modalities(by_type: dict[str, float]) -> dict[str, float]:
    """Per-type accuracy, pooled into the vocabulary the brain reasons in.

    A plain mean over the types in a group rather than a weighted one: the
    question is "does this child do better when they can see it", and a child
    who has done four hundred selection activities and six matching ones has
    answered that question about both.
    """
    grouped: dict[str, list[float]] = {}
    for raw_type, accuracy in by_type.items():
        try:
            modality = TEACHING_MODALITY[ActivityType(raw_type)]
        except (KeyError, ValueError):
            # An `activity_code` from the older manifest planner, whose kinds
            # are a different vocabulary. Dropped rather than guessed at.
            continue
        grouped.setdefault(modality, []).append(accuracy)
    return {modality: sum(values) / len(values) for modality, values in grouped.items()}


def _area_of(skill_code: str) -> str:
    """`color_red` -> `colors`. The starting assessment's area names."""
    prefix, _, _ = skill_code.partition("_")
    return {
        "color": "colors",
        "body": "body_parts",
        "social": "social",
        "hh": "household",
        "num": "numbers",
        "letter": "letters",
    }.get(prefix, prefix)


def _character(row: Any) -> str:
    """`activity_outcomes.character` is CHECKed against two values."""
    return "mano"


def _response_digest(response: dict[str, Any]) -> str:
    """A short, non-identifying record of what the child did.

    Never the raw strokes and never the raw transcript beyond the single word
    the recogniser matched: docs/04d §5 keeps free-form transcripts out of the
    record, and a stroke array is a biometric-adjacent trace with no use once
    the metrics are computed.
    """
    kind = str(response.get("kind", ""))
    match kind:
        case "choice":
            return f"choice:{response.get('option_id', '')}"
        case "count":
            return f"count:{response.get('value', '')}"
        case "sequence":
            return f"sequence:{len(response.get('order', []))}"
        case "sort":
            return f"sort:{len(response.get('assignments', {}))}"
        case "speech":
            return f"speech:{str(response.get('transcript', ''))[:40]}"
        case "strokes":
            return f"strokes:{len(response.get('strokes', []))}"
        case _:
            return kind


def _seed(session_id: UUID, ordinal: int) -> int:
    """Deterministic per (session, position), so a rebuild is identical."""
    return (session_id.int ^ (ordinal * 0x9E3779B1)) & 0xFFFFFFFF


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


__all__ = [
    "CANDIDATE_LIMIT",
    "MAX_SESSION_MINUTES",
    "DeliveredActivity",
    "ResponseResult",
    "TutorService",
]
