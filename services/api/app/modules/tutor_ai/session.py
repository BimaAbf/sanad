"""The play-session orchestrator.

Every AI decision point here has a deterministic fallback, and the session
completes identically whether the model answers, returns nonsense, or is not
called at all. That is the property the whole design rests on, so it is
exercised directly by a chaos test rather than argued for.

Pure orchestration over pure domain code — the persistence layer supplies the
inputs and writes the outputs.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from app.guardrails.layers import GuardrailEvent, enforce_conservatism
from app.modules.learning.domain.bkt import BktState, PromptLevel, bkt_update
from app.modules.learning.domain.candidates import Candidate
from app.modules.learning.domain.mastery import (
    AttemptRecord,
    MasteryInputs,
    MasteryState,
    mastery_rule,
    next_state,
)
from app.modules.tutor_ai.engagement import (
    AffectResponse,
    AttemptSignal,
    EndReason,
    assess,
    should_end,
)
from app.modules.tutor_ai.planning import PlannedActivity, resolve_plan


@dataclass(frozen=True, slots=True)
class IngestedAttempt:
    """One attempt as recorded. `idempotency_key` is client-generated."""

    idempotency_key: str
    skill_id: str
    modality: str
    result: str
    prompt_level: PromptLevel
    choice_count: int
    latency_ms: int
    at: dt.datetime
    selected_skill_id: str | None = None
    position: int = 1


@dataclass(slots=True)
class SkillProgress:
    bkt: BktState
    state: MasteryState
    records: list[AttemptRecord] = field(default_factory=list)
    total_scored: int = 0
    first_correct_at: dt.datetime | None = None
    last_delayed_pass_at: dt.datetime | None = None
    distinct_days: set[dt.date] = field(default_factory=set)


@dataclass(slots=True)
class SessionState:
    session_id: str
    plan: list[PlannedActivity]
    plan_source: str
    plan_rejections: list[str] = field(default_factory=list)
    cursor: int = 0
    attempts: list[IngestedAttempt] = field(default_factory=list)
    seen_keys: set[str] = field(default_factory=set)
    progress: dict[tuple[str, str], SkillProgress] = field(default_factory=dict)
    affect: AffectResponse | None = None
    #: How many activities were done when `affect` was assessed. The affect cap
    #: means "this many MORE from here", so it has to count down from a fixed
    #: point; passing the raw cap through would mean it never reached zero and
    #: a struggling child would never get the shortened session.
    affect_assessed_at: int = 0
    ended_reason: EndReason | None = None
    guardrail_events: list[GuardrailEvent] = field(default_factory=list)
    summary_ar: str | None = None
    #: True when the summary shipped from the template rather than the model.
    summary_is_template: bool = False


def start_session(
    *,
    session_id: str,
    candidates: Sequence[Candidate],
    ai_order: Sequence[str] | None = None,
) -> SessionState:
    plan, source, rejections = resolve_plan(ai_order=ai_order, candidates=candidates)
    return SessionState(
        session_id=session_id, plan=plan, plan_source=source, plan_rejections=list(rejections)
    )


def ingest(
    state: SessionState,
    attempt: IngestedAttempt,
    *,
    existing: SkillProgress | None = None,
) -> tuple[SessionState, bool]:
    """Record one attempt and update BKT. Idempotent on `idempotency_key`.

    Returns (state, applied). `applied` is False for a duplicate, which is the
    normal case when an offline outbox replays — a replayed attempt must produce
    exactly one row and exactly one BKT update.
    """
    if attempt.idempotency_key in state.seen_keys:
        return state, False

    state.seen_keys.add(attempt.idempotency_key)
    state.attempts.append(attempt)

    key = (attempt.skill_id, attempt.modality)
    progress = (
        state.progress.get(key)
        or existing
        or SkillProgress(bkt=BktState(), state=MasteryState.NOT_STARTED)
    )

    correct = attempt.result in ("correct", "caregiver_confirmed", "accepted_on_effort")
    progress.bkt = bkt_update(
        progress.bkt,
        correct=correct,
        choice_count=attempt.choice_count,
        prompt_level=attempt.prompt_level,
    )
    progress.records.append(
        AttemptRecord(
            correct=correct,
            prompt_level=attempt.prompt_level,
            choice_count=attempt.choice_count,
            at=attempt.at,
        )
    )
    if attempt.prompt_level is not PromptLevel.FULL_MODEL:
        progress.total_scored += 1
    progress.distinct_days.add(attempt.at.date())
    if correct:
        if progress.first_correct_at is None:
            progress.first_correct_at = attempt.at
        elif (attempt.at - progress.first_correct_at).days >= 3:
            progress.last_delayed_pass_at = attempt.at

    state.progress[key] = progress
    state.cursor += 1
    return state, True


def update_affect(state: SessionState, baseline_ms: int) -> SessionState:
    signals = [
        AttemptSignal(result=a.result, latency_ms=a.latency_ms, prompt_level=str(a.prompt_level))
        for a in state.attempts
    ]
    state.affect = assess(signals, baseline_ms)
    state.affect_assessed_at = len(state.attempts)
    return state


def check_end(state: SessionState, *, elapsed_seconds: float) -> EndReason | None:
    signals = [
        AttemptSignal(result=a.result, latency_ms=a.latency_ms, prompt_level=str(a.prompt_level))
        for a in state.attempts
    ]
    remaining = None
    extra = 0
    if state.affect is not None:
        extra = state.affect.extra_activities
        if state.affect.cap_remaining is not None:
            # The cap counts DOWN from the point the affect was assessed.
            since = len(state.attempts) - state.affect_assessed_at
            remaining = state.affect.cap_remaining - since
    return should_end(
        elapsed_seconds=elapsed_seconds,
        activities_done=len(state.attempts),
        attempts=signals,
        planned=len(state.plan),
        extra_allowed=extra,
        cap_remaining=remaining,
    )


@dataclass(frozen=True, slots=True)
class JudgeVerdict:
    skill_id: str
    modality: str
    verdict: str
    reason: str = ""


def judge_and_commit(
    state: SessionState,
    *,
    ai_verdicts: Sequence[JudgeVerdict] = (),
) -> list[tuple[tuple[str, str], MasteryState, bool, GuardrailEvent | None]]:
    """Apply the deterministic rule, clamp any AI verdict, and decide transitions.

    The AI can only ever move a verdict from `confirm` to `withhold`. There is no
    code path by which it grants mastery — and the `ai_cannot_grant` CHECK
    constraint backs that up in the database.
    """
    by_skill = {(v.skill_id, v.modality): v for v in ai_verdicts}
    results: list[tuple[tuple[str, str], MasteryState, bool, GuardrailEvent | None]] = []

    for key, progress in state.progress.items():
        deterministic_met = mastery_rule(
            MasteryInputs(
                p_known=progress.bkt.p_known,
                distinct_days=len(progress.distinct_days),
                first_correct_at=progress.first_correct_at,
                last_delayed_pass_at=progress.last_delayed_pass_at,
                attempts=progress.records,
                total_scored_attempts=progress.total_scored,
            )
        )
        deterministic_verdict = "confirm" if deterministic_met else "withhold"

        event: GuardrailEvent | None = None
        ai = by_skill.get(key)
        if ai is not None:
            final, event = enforce_conservatism(ai.verdict, deterministic_verdict)
        else:
            final = deterministic_verdict

        if event is not None:
            state.guardrail_events.append(event)

        new_state = next_state(
            progress.state,
            rule_satisfied=deterministic_met,
            p_known=progress.bkt.p_known,
            ai_withholds=final == "withhold",
        )
        progress.state = new_state
        # rule_satisfied is what the DB constraint checks. It is the
        # DETERMINISTIC verdict, never the AI's.
        results.append((key, new_state, deterministic_met, event))

    return results


# --- session summary --------------------------------------------------------

#: PLACEHOLDER Arabic, agent-written. docs/04c requires four lines of Egyptian
#: Arabic reviewed by a native speaker, and the home activity must come from a
#: fixed household list. → REVIEW-QUEUE.md #6
TEMPLATE_SUMMARY_AR = (
    "لعبتوا {count} ألعاب النهارده.\n"
    "شغل حلو من {child}.\n"
    "نكمّل مع بعض بكرة.\n"
    "جرّبوا كده الليلة: هاتوا حاجة من البيت واسألوا عنها مع بعض."
)

#: Household objects a home activity may name. Fixed, so a model cannot invent
#: an object a family does not own.
HOME_ACTIVITY_OBJECTS: tuple[str, ...] = (
    "فرشة سنان",
    "كوباية",
    "معلقة",
    "طبق",
    "فوطة",
    "مشط",
    "جزمة",
    "شنطة",
)


# The default is the pseudonymisation placeholder, not a credential.
def template_summary(activity_count: int, child_token: str = "{{CHILD}}") -> str:  # noqa: S107
    """The summary that ships whenever the model is unavailable or rejected."""
    return TEMPLATE_SUMMARY_AR.format(count=activity_count, child=child_token)


def summary_violations(summary: str, *, activity_count: int) -> list[str]:
    """Constraints from docs/04c §C07: no numbers except the activity count."""
    import re

    problems: list[str] = []
    lines = [line for line in summary.strip().splitlines() if line.strip()]
    if len(lines) != 4:
        problems.append(f"summary has {len(lines)} lines, must have 4")

    from app.guardrails.layers import normalise_number

    allowed = {normalise_number(str(activity_count))}
    for token in re.findall(r"[\d٠-٩]+", summary):
        if normalise_number(token) not in allowed:
            problems.append(f"contains a number that is not the activity count: {token}")

    return problems


def resolve_summary(*, ai_summary: str | None, activity_count: int) -> tuple[str, bool, list[str]]:
    """(summary, is_template, why the AI's was rejected)."""
    fallback = template_summary(activity_count)
    if not ai_summary:
        return fallback, True, ["no ai summary"]
    problems = summary_violations(ai_summary, activity_count=activity_count)
    if problems:
        return fallback, True, problems
    return ai_summary, False, []


def finish(state: SessionState, *, ai_summary: str | None = None) -> SessionState:
    summary, is_template, _problems = resolve_summary(
        ai_summary=ai_summary, activity_count=len(state.attempts)
    )
    state.summary_ar = summary
    state.summary_is_template = is_template
    if state.ended_reason is None:
        state.ended_reason = EndReason.COMPLETED
    return state


def drain_outbox(
    state: SessionState, batch: Sequence[IngestedAttempt]
) -> tuple[SessionState, int, int]:
    """Absorb an offline batch. Returns (state, applied, duplicates).

    A replayed outbox must lose zero attempts and create zero duplicates. The
    unique index on `attempts.idempotency_key` is the database-level backstop;
    this is the application-level one.
    """
    applied = duplicates = 0
    for attempt in batch:
        state, was_applied = ingest(state, attempt)
        if was_applied:
            applied += 1
        else:
            duplicates += 1
    return state, applied, duplicates


def snapshot(state: SessionState) -> SessionState:
    """A shallow copy for checkpointing."""
    return replace(state)
