"""P08 tutor orchestrator: planning, engagement, judging, offline drain.

The tests that carry weight:
  * an AI "confirm" against an unmet deterministic rule produces NO transition
  * the evidence bundle contains no name, no diagnosis, no age in years
  * 3 consecutive no_response always ends the session, never mid-activity
  * replaying the outbox loses zero attempts and creates zero duplicates
  * a scripted child runs 30 sessions with the AI stubbed off entirely
"""

from __future__ import annotations

import datetime as dt
import json

from app.guardrails.layers import Outcome
from app.modules.learning.domain.bkt import PromptLevel
from app.modules.learning.domain.candidates import Candidate, CandidateKind
from app.modules.learning.domain.mastery import MasteryState
from app.modules.tutor_ai.engagement import (
    MAX_ACTIVITIES,
    MAX_CONSECUTIVE_NO_RESPONSE,
    MAX_SESSION_SECONDS,
    Affect,
    AttemptSignal,
    EndReason,
    assess,
    classify,
    engagement,
    should_end,
)
from app.modules.tutor_ai.evidence import (
    FORBIDDEN_BUNDLE_KEYS,
    RawAttempt,
    build_bundle,
    forbidden_keys_present,
)
from app.modules.tutor_ai.planning import (
    NEW_SKILL_MAX_POSITION,
    NEW_SKILL_MIN_POSITION,
    deterministic_plan,
    resolve_plan,
    violations,
)
from app.modules.tutor_ai.session import (
    HOME_ACTIVITY_OBJECTS,
    IngestedAttempt,
    JudgeVerdict,
    check_end,
    drain_outbox,
    finish,
    ingest,
    judge_and_commit,
    resolve_summary,
    start_session,
    summary_violations,
    template_summary,
    update_affect,
)

NOW = dt.datetime(2026, 6, 1, 16, 0, tzinfo=dt.UTC)


def _candidate(skill_id: str, kind: CandidateKind, modality: str = "receptive") -> Candidate:
    return Candidate(skill_id=skill_id, modality=modality, kind=kind, priority=0)


CANDIDATES = [
    _candidate("mastered_a", CandidateKind.CONFIDENCE),
    _candidate("due_1", CandidateKind.DUE),
    _candidate("due_2", CandidateKind.DUE),
    _candidate("due_3", CandidateKind.DUE),
    _candidate("new_1", CandidateKind.NEW),
    _candidate("lapsed_1", CandidateKind.LAPSED),
]


# ============================================================================
# Planning
# ============================================================================


def test_the_deterministic_plan_satisfies_every_constraint() -> None:
    """The fallback must always be legal — it is what ships when the AI fails."""
    plan = deterministic_plan(CANDIDATES)
    assert violations(plan, CANDIDATES) == []


def test_the_plan_opens_and_closes_on_a_mastered_skill() -> None:
    plan = deterministic_plan(CANDIDATES)
    assert plan[0].kind is CandidateKind.CONFIDENCE
    assert plan[-1].kind is CandidateKind.CONFIDENCE


def test_the_new_skill_sits_in_position_three_to_five() -> None:
    plan = deterministic_plan(CANDIDATES)
    positions = [index for index, a in enumerate(plan, start=1) if a.kind is CandidateKind.NEW]
    assert positions
    for position in positions:
        assert NEW_SKILL_MIN_POSITION <= position <= NEW_SKILL_MAX_POSITION


def test_never_two_expressive_activities_in_a_row() -> None:
    candidates = [
        _candidate("m", CandidateKind.CONFIDENCE),
        _candidate("e1", CandidateKind.DUE, "expressive"),
        _candidate("e2", CandidateKind.DUE, "expressive"),
        _candidate("r1", CandidateKind.DUE, "receptive"),
    ]
    plan = deterministic_plan(candidates)
    modalities = [a.modality for a in plan]
    assert not any(
        modalities[i] == modalities[i + 1] == "expressive" for i in range(len(modalities) - 1)
    )


def test_an_ai_plan_that_adds_an_id_is_rejected() -> None:
    """The AI may reorder. It may never add."""
    plan, source, problems = resolve_plan(
        ai_order=["mastered_a", "invented_skill"], candidates=CANDIDATES
    )
    assert source == "deterministic_fallback"
    assert problems
    assert violations(plan, CANDIDATES) == []


def test_an_ai_plan_that_duplicates_an_id_is_rejected() -> None:
    _plan, source, _ = resolve_plan(
        ai_order=["mastered_a", "due_1", "due_1"], candidates=CANDIDATES
    )
    assert source == "deterministic_fallback"


def test_an_ai_plan_that_breaks_the_opening_rule_is_rejected() -> None:
    _plan, source, problems = resolve_plan(
        ai_order=["due_1", "due_2", "new_1", "due_3", "mastered_a"],
        candidates=CANDIDATES,
    )
    assert source == "deterministic_fallback"
    assert any("open" in p for p in problems)


def test_an_ai_plan_that_misplaces_the_new_skill_is_rejected() -> None:
    _plan, source, problems = resolve_plan(
        ai_order=["mastered_a", "new_1", "due_1", "due_2", "mastered_a"],
        candidates=CANDIDATES,
    )
    assert source == "deterministic_fallback"
    assert any("new skill" in p for p in problems)


def test_a_legal_ai_reordering_is_accepted() -> None:
    """The AI's value is small but real; when it obeys, its ordering ships."""
    order = ["mastered_a", "due_2", "new_1", "due_1", "lapsed_1", "due_3", "mastered_a"]
    # Same skill cannot repeat, so close on a different mastered item.
    candidates = [*CANDIDATES, _candidate("mastered_b", CandidateKind.CONFIDENCE)]
    order[-1] = "mastered_b"
    plan, source, problems = resolve_plan(ai_order=order, candidates=candidates)
    assert problems == [], problems
    assert source == "ai"
    assert [a.skill_id for a in plan] == order


def test_no_ai_plan_falls_back_silently() -> None:
    plan, source, _ = resolve_plan(ai_order=None, candidates=CANDIDATES)
    assert source == "deterministic_fallback"
    assert plan


def test_an_empty_candidate_set_produces_an_empty_plan() -> None:
    assert deterministic_plan([]) == []
    assert violations([], []) == ["plan is empty"]


# ============================================================================
# Engagement heuristic
# ============================================================================


def _signal(result: str = "correct", latency: int = 4000, level: str = "independent"):  # type: ignore[no-untyped-def]
    return AttemptSignal(result=result, latency_ms=latency, prompt_level=level)


def test_two_no_responses_means_struggling() -> None:
    signals = engagement([_signal("no_response"), _signal("no_response")], 4000)
    assert classify(signals) is Affect.STRUGGLING


def test_three_errors_in_a_row_means_struggling() -> None:
    signals = engagement([_signal("incorrect") for _ in range(3)], 4000)
    assert classify(signals) is Affect.STRUGGLING


def test_slow_responses_mean_tiring() -> None:
    signals = engagement([_signal(latency=9000) for _ in range(3)], 4000)
    assert classify(signals) is Affect.TIRING


def test_climbing_the_prompt_ladder_means_tiring() -> None:
    signals = engagement([_signal(level="partial_verbal") for _ in range(3)], 4000)
    assert classify(signals) is Affect.TIRING


def test_fast_and_correct_means_flowing() -> None:
    signals = engagement([_signal(latency=2000) for _ in range(3)], 4000)
    assert classify(signals) is Affect.FLOWING


def test_the_default_is_steady() -> None:
    signals = engagement([_signal(latency=4000)], 4000)
    assert classify(signals) is Affect.STEADY


def test_no_attempts_yet_is_steady() -> None:
    assert classify(engagement([], 4000)) is Affect.STEADY


def test_struggling_beats_tiring_when_both_apply() -> None:
    """A struggling child must get the struggling response, not the tiring one."""
    signals = engagement([_signal("no_response", 12000, "full_model") for _ in range(3)], 4000)
    assert classify(signals) is Affect.STRUGGLING


def test_the_struggling_response_makes_the_session_easier_not_harder() -> None:
    response = assess([_signal("no_response"), _signal("no_response")], 4000)
    assert response.insert_confidence_item
    assert response.force_choice_count == 2
    assert response.advance_prompt_ladder
    assert response.cap_remaining == 3


def test_the_tiring_response_lengthens_the_wait_and_drops_the_new_skill() -> None:
    response = assess([_signal(latency=9000) for _ in range(3)], 4000)
    assert response.cap_remaining == 4
    assert response.skip_new_skill
    assert response.wait_time_multiplier == 1.25


def test_the_flowing_response_only_extends_within_the_hard_limits() -> None:
    response = assess([_signal(latency=2000) for _ in range(3)], 4000)
    assert response.extra_activities == 2
    assert response.allow_extra_choice_on_mastered
    # Even flowing cannot exceed the hard cap.
    assert (
        should_end(
            elapsed_seconds=0,
            activities_done=MAX_ACTIVITIES,
            attempts=[_signal(latency=2000)],
            planned=100,
            extra_allowed=response.extra_activities,
        )
        is EndReason.COMPLETED
    )


def test_a_zero_baseline_does_not_divide_by_zero() -> None:
    assert engagement([_signal(latency=4000)], 0).latency_drift > 0


# --- hard limits ------------------------------------------------------------


def test_three_consecutive_no_responses_always_ends_the_session() -> None:
    """P08: '3 consecutive no_response always ends the session warmly'."""
    attempts = [_signal("correct")] + [
        _signal("no_response") for _ in range(MAX_CONSECUTIVE_NO_RESPONSE)
    ]
    assert (
        should_end(elapsed_seconds=0, activities_done=4, attempts=attempts, planned=100)
        is EndReason.FATIGUE
    )


def test_two_no_responses_do_not_end_the_session() -> None:
    attempts = [_signal("no_response"), _signal("no_response")]
    assert should_end(elapsed_seconds=0, activities_done=2, attempts=attempts, planned=100) is None


def test_a_correct_answer_resets_the_no_response_run() -> None:
    attempts = [
        _signal("no_response"),
        _signal("no_response"),
        _signal("correct"),
        _signal("no_response"),
    ]
    assert should_end(elapsed_seconds=0, activities_done=4, attempts=attempts, planned=100) is None


def test_the_ten_minute_wall_clock_ends_the_session() -> None:
    assert (
        should_end(
            elapsed_seconds=MAX_SESSION_SECONDS,
            activities_done=2,
            attempts=[_signal()],
            planned=100,
        )
        is EndReason.TIMEOUT
    )


def test_fifteen_activities_ends_the_session() -> None:
    assert (
        should_end(
            elapsed_seconds=0,
            activities_done=MAX_ACTIVITIES,
            attempts=[_signal()],
            planned=100,
        )
        is EndReason.COMPLETED
    )


def test_an_affect_cap_ends_the_session_early() -> None:
    assert (
        should_end(
            elapsed_seconds=0,
            activities_done=1,
            attempts=[_signal()],
            planned=100,
            cap_remaining=0,
        )
        is EndReason.FATIGUE
    )


def test_the_session_ends_when_the_plan_is_finished() -> None:
    assert (
        should_end(elapsed_seconds=0, activities_done=5, attempts=[_signal()], planned=5)
        is EndReason.COMPLETED
    )


# ============================================================================
# The evidence bundle
# ============================================================================


def _raw(day_offset: int, result: str = "correct") -> RawAttempt:
    return RawAttempt(
        at=NOW + dt.timedelta(days=day_offset),
        result=result,
        latency_ms=4100,
        prompt_level="independent",
        choice_count=2,
        position=1,
    )


def test_the_bundle_contains_no_name_diagnosis_or_age_in_years() -> None:
    """P08: assert by scanning the outgoing payload, not by convention.

    The judge does not know the child has Down syndrome. That is deliberate —
    expectation effects are real in models as in people.
    """
    bundle = build_bundle(
        skill_code="color_red",
        modality="receptive",
        deterministic_rule_met=True,
        p_known=0.93,
        attempts=[_raw(-6), _raw(-3, "incorrect"), _raw(0)],
        baseline_latency_ms=4300,
        now=NOW,
    )
    payload = bundle.to_dict()
    assert forbidden_keys_present(payload) == []

    serialised = json.dumps(payload, ensure_ascii=False).lower()
    for term in ("down", "syndrome", "diagnos", "autism", "يوسف", "سنة"):
        assert term not in serialised, f"{term!r} reached the judge"


def test_the_forbidden_key_scan_actually_finds_things() -> None:
    """Guard against the previous test passing because the scan is broken."""
    assert forbidden_keys_present({"a": {"diagnosis": "x"}}) == ["a.diagnosis"]
    assert forbidden_keys_present([{"age_years": 4}]) == ["[0].age_years"]
    assert "diagnosis" in FORBIDDEN_BUNDLE_KEYS


def test_the_bundle_keeps_what_makes_the_judgement_possible() -> None:
    """Position, the specific wrong choice, and latency vs the child's baseline."""
    attempts = [
        RawAttempt(
            at=NOW,
            result="incorrect",
            latency_ms=900,
            prompt_level="independent",
            choice_count=3,
            position=2,
            selected_skill_id="color_orange",
        )
    ]
    bundle = build_bundle(
        skill_code="color_red",
        modality="receptive",
        deterministic_rule_met=False,
        p_known=0.4,
        attempts=attempts,
        baseline_latency_ms=4300,
        now=NOW,
    )
    entry = bundle.to_dict()["attempts"][0]
    assert entry["position"] == 2
    assert entry["selected"] == "color_orange"
    assert bundle.to_dict()["baseline_latency_ms"] == 4300


def test_absolute_timestamps_become_day_offsets() -> None:
    """An absolute timestamp is quasi-identifying when combined with anything."""
    bundle = build_bundle(
        skill_code="s",
        modality="receptive",
        deterministic_rule_met=False,
        p_known=0.5,
        attempts=[_raw(-6), _raw(0)],
        baseline_latency_ms=4000,
        now=NOW,
    )
    offsets = [a["day_offset"] for a in bundle.to_dict()["attempts"]]
    assert offsets == [-6, 0]
    assert "2026" not in json.dumps(bundle.to_dict())


def test_delayed_retrieval_is_measured_between_correct_answers() -> None:
    bundle = build_bundle(
        skill_code="s",
        modality="receptive",
        deterministic_rule_met=True,
        p_known=0.9,
        attempts=[_raw(-6), _raw(-3, "incorrect"), _raw(0)],
        baseline_latency_ms=4000,
        now=NOW,
    )
    assert bundle.delayed_retrieval_days == 6
    assert bundle.distinct_days == 3


def test_a_bundle_with_no_correct_answers_reports_zero_delay() -> None:
    bundle = build_bundle(
        skill_code="s",
        modality="receptive",
        deterministic_rule_met=False,
        p_known=0.2,
        attempts=[_raw(0, "incorrect")],
        baseline_latency_ms=4000,
        now=NOW,
    )
    assert bundle.delayed_retrieval_days == 0


# ============================================================================
# Judging — the assertion that matters most
# ============================================================================


def _attempt(key: str, skill: str = "s1", correct: bool = True, day: int = 0, choices: int = 3):  # type: ignore[no-untyped-def]
    """Three choices by default.

    At two choices a coin flip is already half right, so the anytime-valid
    accuracy guard needs ~30 attempts before it will credit mastery. These tests
    are about the JUDGE, not about that threshold, so they use the realistic
    3-choice case. The 2-choice cost is measured in
    tests/unit/test_bkt_random_tapper.py and reported in REVIEW-QUEUE #5.
    """
    return IngestedAttempt(
        idempotency_key=key,
        skill_id=skill,
        modality="receptive",
        result="correct" if correct else "incorrect",
        prompt_level=PromptLevel.INDEPENDENT,
        choice_count=choices,
        latency_ms=4000,
        at=NOW + dt.timedelta(days=day),
    )


def test_an_ai_confirm_against_an_unmet_rule_produces_no_transition() -> None:
    """P08: 'the AI judge returning confirm when the deterministic rule is unmet
    results in NO mastery transition, a clamp guardrail event, and an alert'.
    """
    state = start_session(session_id="s", candidates=CANDIDATES)
    state, _ = ingest(state, _attempt("k1"))

    results = judge_and_commit(
        state,
        ai_verdicts=[JudgeVerdict("s1", "receptive", "confirm", "looks mastered to me")],
    )

    (_key, new_state, rule_satisfied, event) = results[0]
    assert new_state is not MasteryState.MASTERED
    assert rule_satisfied is False, "the DB constraint checks the DETERMINISTIC verdict"
    assert event is not None
    assert event.layer == "monotonicity"
    assert event.outcome is Outcome.REPAIRED
    assert state.guardrail_events, "the clamp must be recorded for alerting"


def test_an_ai_withhold_against_a_met_rule_blocks_the_transition() -> None:
    """The AI may always be MORE conservative."""
    state = start_session(session_id="s", candidates=CANDIDATES)
    for index in range(20):
        state, _ = ingest(state, _attempt(f"k{index}", day=index // 2))

    with_ai = judge_and_commit(
        state, ai_verdicts=[JudgeVerdict("s1", "receptive", "withhold", "position bias")]
    )
    assert with_ai[0][1] is not MasteryState.MASTERED
    # The deterministic rule itself was satisfied; only the AI held it back.
    assert with_ai[0][2] is True


def test_with_no_ai_verdict_the_deterministic_rule_decides_alone() -> None:
    state = start_session(session_id="s", candidates=CANDIDATES)
    for index in range(20):
        state, _ = ingest(state, _attempt(f"k{index}", day=index // 2))
    results = judge_and_commit(state)
    assert results[0][1] is MasteryState.MASTERED


def test_a_nonsense_ai_verdict_collapses_to_withhold() -> None:
    state = start_session(session_id="s", candidates=CANDIDATES)
    for index in range(20):
        state, _ = ingest(state, _attempt(f"k{index}", day=index // 2))
    results = judge_and_commit(
        state, ai_verdicts=[JudgeVerdict("s1", "receptive", "absolutely_yes")]
    )
    assert results[0][1] is not MasteryState.MASTERED


# ============================================================================
# Idempotency and the offline outbox
# ============================================================================


def test_replaying_an_attempt_produces_one_row_and_one_bkt_update() -> None:
    """P07/P08: same idempotency key twice -> one row, one update."""
    state = start_session(session_id="s", candidates=CANDIDATES)
    state, first = ingest(state, _attempt("same-key"))
    p_after_first = state.progress[("s1", "receptive")].bkt.p_known

    state, second = ingest(state, _attempt("same-key"))
    p_after_second = state.progress[("s1", "receptive")].bkt.p_known

    assert first is True
    assert second is False
    assert len(state.attempts) == 1
    assert p_after_first == p_after_second


def test_draining_an_outbox_loses_nothing_and_duplicates_nothing() -> None:
    """P08: 'killing the network mid-session and replaying loses zero attempts
    and creates zero duplicates'.
    """
    state = start_session(session_id="s", candidates=CANDIDATES)
    batch = [_attempt(f"k{i}") for i in range(10)]

    state, applied, duplicates = drain_outbox(state, batch[:6])
    assert (applied, duplicates) == (6, 0)

    # The client reconnects and replays the WHOLE outbox, as it must when it
    # cannot know which writes landed.
    state, applied, duplicates = drain_outbox(state, batch)
    assert applied == 4, "the four unseen attempts must land"
    assert duplicates == 6, "the six already-seen attempts must be absorbed"
    assert len(state.attempts) == 10


def test_a_full_outbox_replay_after_a_total_failure_lands_everything() -> None:
    state = start_session(session_id="s", candidates=CANDIDATES)
    batch = [_attempt(f"k{i}") for i in range(100)]
    state, applied, duplicates = drain_outbox(state, batch)
    assert (applied, duplicates) == (100, 0)


# ============================================================================
# Summary
# ============================================================================


def test_the_template_summary_is_four_lines() -> None:
    summary = template_summary(8)
    assert len([line for line in summary.splitlines() if line.strip()]) == 4


def test_the_summary_carries_no_number_except_the_activity_count() -> None:
    assert summary_violations(template_summary(8), activity_count=8) == []
    bad = "لعبتوا 8 ألعاب.\nوصل لمستوى 36 شهر.\nتالت سطر.\nرابع سطر."
    problems = summary_violations(bad, activity_count=8)
    assert any("36" in p for p in problems)


def test_a_summary_with_the_wrong_line_count_is_rejected() -> None:
    problems = summary_violations("سطر واحد بس", activity_count=8)
    assert any("lines" in p for p in problems)


def test_an_invalid_ai_summary_falls_back_to_the_template() -> None:
    summary, is_template, problems = resolve_summary(ai_summary="طفلك وصل 36 شهر", activity_count=8)
    assert is_template
    assert problems
    assert summary == template_summary(8)


def test_a_missing_ai_summary_falls_back_silently() -> None:
    summary, is_template, _ = resolve_summary(ai_summary=None, activity_count=5)
    assert is_template
    assert "5" in summary


def test_the_home_activity_object_list_is_fixed_and_from_the_curriculum() -> None:
    """A model must not invent an object a family does not own."""
    from seeds.curriculum import HOUSEHOLD

    household_labels = {label for _code, label in HOUSEHOLD}
    assert set(HOME_ACTIVITY_OBJECTS) <= household_labels


# ============================================================================
# The chaos test: every AI node off
# ============================================================================


def test_a_full_session_completes_with_every_ai_node_disabled() -> None:
    """P08: 'with the tutor_plan flag off, sessions still run with deterministic
    ordering and no user-visible difference beyond ordering'.
    """
    state = start_session(session_id="s", candidates=CANDIDATES, ai_order=None)
    assert state.plan_source == "deterministic_fallback"

    for index, activity in enumerate(state.plan):
        state, _ = ingest(
            state,
            IngestedAttempt(
                idempotency_key=f"chaos-{index}",
                skill_id=activity.skill_id,
                modality=activity.modality,
                result="correct",
                prompt_level=PromptLevel.INDEPENDENT,
                choice_count=2,
                latency_ms=4000,
                at=NOW + dt.timedelta(minutes=index),
            ),
        )
        state = update_affect(state, baseline_ms=4000)

    # No AI verdicts, no AI summary — nothing at all.
    judge_and_commit(state, ai_verdicts=[])
    state = finish(state, ai_summary=None)

    assert state.summary_ar
    assert state.summary_is_template
    assert state.ended_reason is EndReason.COMPLETED
    assert len(state.attempts) == len(state.plan)


# ============================================================================
# The 30-session simulation
# ============================================================================


def test_a_scripted_child_runs_thirty_sessions_with_a_sane_mastery_curve() -> None:
    """P08: 'a scripted simulated child runs 30 sessions end to end with AI
    stubbed and produces a monotonically sensible mastery curve'.
    """
    import random

    rng = random.Random(4)
    skills = [f"skill_{i}" for i in range(8)]
    # Persistent per-skill progress across sessions.
    carried: dict[tuple[str, str], object] = {}
    mastered_over_time: list[int] = []
    day = 0

    for session_index in range(30):
        candidates = [
            _candidate(skill, CandidateKind.DUE if i else CandidateKind.CONFIDENCE)
            for i, skill in enumerate(skills[: 3 + session_index // 6])
        ]
        state = start_session(session_id=f"s{session_index}", candidates=candidates)
        for key, progress in carried.items():
            state.progress[key] = progress  # type: ignore[assignment]

        for index, activity in enumerate(state.plan):
            # A child who is genuinely learning: accuracy rises with exposure.
            seen = len(getattr(carried.get((activity.skill_id, activity.modality)), "records", []))
            accuracy = min(0.55 + 0.05 * seen, 0.97)
            state, _ = ingest(
                state,
                IngestedAttempt(
                    idempotency_key=f"{session_index}-{index}",
                    skill_id=activity.skill_id,
                    modality=activity.modality,
                    result="correct" if rng.random() < accuracy else "incorrect",
                    prompt_level=PromptLevel.INDEPENDENT,
                    choice_count=3,
                    latency_ms=4000,
                    at=NOW + dt.timedelta(days=day, minutes=index),
                ),
            )
        judge_and_commit(state)
        state = finish(state)
        carried.update(state.progress)
        day += 2

        mastered_over_time.append(
            sum(1 for p in carried.values() if p.state is MasteryState.MASTERED)  # type: ignore[attr-defined]
        )

    assert len(mastered_over_time) == 30
    # Sensible: it grows, and it never collapses. A drop is possible via lapse,
    # so this asserts the curve ends higher than it started rather than being
    # strictly monotonic, which would be the wrong claim.
    assert mastered_over_time[-1] > 0, "a learning child mastered nothing in 30 sessions"
    assert mastered_over_time[-1] >= mastered_over_time[0]
    assert max(mastered_over_time) <= len(skills)


def test_the_simulation_would_notice_a_broken_engine() -> None:
    """A child answering everything wrong must master nothing over 30 sessions."""
    import random

    rng = random.Random(4)
    carried: dict[tuple[str, str], object] = {}
    for session_index in range(30):
        candidates = [
            _candidate("only", CandidateKind.CONFIDENCE),
            _candidate("target", CandidateKind.DUE),
        ]
        state = start_session(session_id=f"s{session_index}", candidates=candidates)
        for key, progress in carried.items():
            state.progress[key] = progress  # type: ignore[assignment]
        for index, activity in enumerate(state.plan):
            state, _ = ingest(
                state,
                IngestedAttempt(
                    idempotency_key=f"{session_index}-{index}",
                    skill_id=activity.skill_id,
                    modality=activity.modality,
                    result="incorrect",
                    prompt_level=PromptLevel.INDEPENDENT,
                    choice_count=2,
                    latency_ms=4000,
                    at=NOW + dt.timedelta(days=session_index * 2, minutes=index),
                ),
            )
        judge_and_commit(state)
        carried.update(state.progress)
        rng.random()

    assert all(
        p.state is not MasteryState.MASTERED
        for p in carried.values()  # type: ignore[attr-defined]
    )


# ============================================================================
# Remaining branches — real edge cases
# ============================================================================


def test_a_plan_where_nothing_can_follow_still_keeps_every_activity() -> None:
    """A slightly worse ordering beats a shorter session.

    Two expressive activities on the same skill cannot be separated, but the
    child must still get both — dropping one would silently shorten the session.
    """
    candidates = [
        _candidate("only", CandidateKind.DUE, "expressive"),
        _candidate("only", CandidateKind.DUE, "expressive"),
    ]
    plan = deterministic_plan(candidates)
    assert len(plan) == 2, "an activity was dropped rather than reordered"


def test_may_follow_permits_a_receptive_after_an_expressive() -> None:
    from app.modules.tutor_ai.planning import _may_follow

    expressive = _candidate("a", CandidateKind.DUE, "expressive")
    receptive = _candidate("b", CandidateKind.DUE, "receptive")
    assert _may_follow(expressive, receptive)
    assert _may_follow(None, expressive)
    assert not _may_follow(expressive, _candidate("a", CandidateKind.DUE, "expressive"))


def test_an_ai_plan_repeating_a_skill_back_to_back_is_rejected() -> None:
    candidates = [
        _candidate("m", CandidateKind.CONFIDENCE),
        _candidate("d", CandidateKind.DUE),
    ]
    problems = violations(
        [
            deterministic_plan(candidates)[0],
            deterministic_plan(candidates)[0],
        ],
        candidates,
    )
    assert any("back to back" in p for p in problems)


def test_check_end_respects_an_affect_cap_and_a_flowing_extension() -> None:
    """check_end must read the affect that update_affect recorded."""
    state = start_session(session_id="s", candidates=CANDIDATES)
    for index in range(3):
        state, _ = ingest(
            state,
            IngestedAttempt(
                idempotency_key=f"tired-{index}",
                skill_id="s1",
                modality="receptive",
                result="incorrect",
                prompt_level=PromptLevel.INDEPENDENT,
                choice_count=2,
                latency_ms=4000,
                at=NOW,
            ),
        )
    state = update_affect(state, baseline_ms=4000)
    assert state.affect is not None
    assert state.affect.affect is Affect.STRUGGLING
    assert state.affect.cap_remaining == 3

    # The cap means THREE MORE from here, so it must not fire immediately...
    assert check_end(state, elapsed_seconds=10) is None

    # ...and must fire once those three have happened.
    for index in range(3):
        state, _ = ingest(
            state,
            IngestedAttempt(
                idempotency_key=f"after-{index}",
                skill_id="s2",
                modality="receptive",
                result="correct",
                prompt_level=PromptLevel.INDEPENDENT,
                choice_count=2,
                latency_ms=4000,
                at=NOW,
            ),
        )
    assert check_end(state, elapsed_seconds=10) is EndReason.FATIGUE


def test_check_end_before_any_affect_is_assessed() -> None:
    state = start_session(session_id="s", candidates=CANDIDATES)
    assert state.affect is None
    assert check_end(state, elapsed_seconds=0) is None


def test_check_end_ends_on_the_wall_clock_regardless_of_affect() -> None:
    state = start_session(session_id="s", candidates=CANDIDATES)
    state, _ = ingest(state, _attempt("k0"))
    state = update_affect(state, baseline_ms=4000)
    assert check_end(state, elapsed_seconds=MAX_SESSION_SECONDS) is EndReason.TIMEOUT


def test_a_valid_ai_summary_ships_unchanged() -> None:
    good = "لعبتوا 6 ألعاب النهارده.\nشغل حلو أوي.\nنكمّل بكرة.\nجرّبوا الليلة مع الكوباية."
    summary, is_template, problems = resolve_summary(ai_summary=good, activity_count=6)
    assert problems == []
    assert not is_template
    assert summary == good


def test_finish_preserves_an_already_set_end_reason() -> None:
    """A fatigue ending must not be overwritten as 'completed'."""
    state = start_session(session_id="s", candidates=CANDIDATES)
    state.ended_reason = EndReason.FATIGUE
    state = finish(state)
    assert state.ended_reason is EndReason.FATIGUE


def test_a_snapshot_can_be_taken_for_checkpointing() -> None:
    from app.modules.tutor_ai.session import snapshot

    state = start_session(session_id="s", candidates=CANDIDATES)
    state, _ = ingest(state, _attempt("k0"))
    copy = snapshot(state)
    assert copy.session_id == state.session_id
    assert len(copy.attempts) == 1


def test_an_attempt_carrying_existing_progress_continues_it() -> None:
    """Progress carried in from a previous session must not restart at zero."""
    from app.modules.learning.domain.bkt import BktState
    from app.modules.tutor_ai.session import SkillProgress

    prior = SkillProgress(bkt=BktState(p_known=0.8), state=MasteryState.PRACTISING)
    state = start_session(session_id="s", candidates=CANDIDATES)
    state, _ = ingest(state, _attempt("k0"), existing=prior)
    assert state.progress[("s1", "receptive")].bkt.p_known > 0.8


def test_accepted_on_effort_and_caregiver_confirmed_count_as_correct() -> None:
    """A child who tried and a caregiver who confirmed are both successes."""
    for result in ("accepted_on_effort", "caregiver_confirmed"):
        state = start_session(session_id="s", candidates=CANDIDATES)
        state, _ = ingest(
            state,
            IngestedAttempt(
                idempotency_key=f"k-{result}",
                skill_id="s1",
                modality="receptive",
                result=result,
                prompt_level=PromptLevel.INDEPENDENT,
                choice_count=2,
                latency_ms=4000,
                at=NOW,
            ),
        )
        assert state.progress[("s1", "receptive")].records[0].correct is True


def test_a_full_model_attempt_is_recorded_but_not_scored() -> None:
    state = start_session(session_id="s", candidates=CANDIDATES)
    state, _ = ingest(
        state,
        IngestedAttempt(
            idempotency_key="fm",
            skill_id="s1",
            modality="receptive",
            result="correct",
            prompt_level=PromptLevel.FULL_MODEL,
            choice_count=2,
            latency_ms=4000,
            at=NOW,
        ),
    )
    progress = state.progress[("s1", "receptive")]
    assert len(progress.records) == 1, "it must still be recorded"
    assert progress.total_scored == 0, "but it must not count toward accuracy"


def test_a_single_activity_plan_needs_only_a_mastered_opener() -> None:
    """With one activity there is no separate 'close'; opening on it is enough."""
    candidates = [_candidate("m", CandidateKind.CONFIDENCE)]
    plan = deterministic_plan(candidates)
    assert len(plan) == 1
    assert violations(plan, candidates) == []


def test_a_plan_with_no_mastered_skill_available_skips_the_bookend_rule() -> None:
    """A brand-new child has mastered nothing; the session must still run."""
    candidates = [
        _candidate("d1", CandidateKind.DUE),
        _candidate("d2", CandidateKind.DUE),
    ]
    plan = deterministic_plan(candidates)
    assert len(plan) == 2
    assert violations(plan, candidates) == []


def test_two_expressive_in_a_row_is_reported_by_the_validator() -> None:
    from app.modules.tutor_ai.planning import PlannedActivity

    candidates = [
        _candidate("a", CandidateKind.DUE, "expressive"),
        _candidate("b", CandidateKind.DUE, "expressive"),
    ]
    bad = [
        PlannedActivity("a", "expressive", CandidateKind.DUE),
        PlannedActivity("b", "expressive", CandidateKind.DUE),
    ]
    assert any("two expressive" in p for p in violations(bad, candidates))
