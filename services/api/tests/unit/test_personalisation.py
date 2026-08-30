"""Twenty-two synthetic learners, and the differences their evidence produces.

The claim this file exists to test is the one the whole product rests on:

    a different learner state produces a different session, and it does so
    BECAUSE of the evidence rather than because of who the child is.

So there are no names anywhere below. Every scenario is a `LearnerEvidence`
bundle and a candidate set, and the assertions are about what changes between
two bundles that differ in exactly one dimension. If someone were to add

    if child.name == "Ahmed": give_easy_activity()

nothing in this file would notice, because nothing in this file has a name to
give it — which is the point. The database-backed counterpart, where three
seeded children with real histories are shown to get different sessions, is
`tests/integration/test_tutor_loop.py`.

Every decision goes through `guard_decision`, so what is asserted is the
decision that would actually be delivered, not the raw fallback.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from app.modules.learning.domain.candidates import Candidate, CandidateKind
from app.modules.tutor.domain.contract import TEACHING_MODALITY, ActivityType
from app.modules.tutor_ai.brain import (
    BrainAction,
    BrainDecision,
    LearnerEvidence,
    SupportLevel,
    TeachingStrategy,
    decide,
)

RECEPTIVE = "receptive"

#: A candidate set wide enough that the decision has somewhere to go: one skill
#: under review, one new, one already mastered.
CANDIDATES: tuple[Candidate, ...] = (
    Candidate(skill_id="colour_red", modality=RECEPTIVE, kind=CandidateKind.DUE, priority=0),
    Candidate(skill_id="colour_blue", modality=RECEPTIVE, kind=CandidateKind.NEW, priority=0),
    Candidate(skill_id="body_head", modality=RECEPTIVE, kind=CandidateKind.CONFIDENCE, priority=0),
)

ALL_TYPES = tuple(str(value) for value in ActivityType)

#: Every type whose teaching modality is visual. Taken from the table rather
#: than listed, so a new visual activity type joins these assertions instead of
#: quietly falsifying them.
VISUAL_TYPES = frozenset(
    str(activity_type)
    for activity_type, modality in TEACHING_MODALITY.items()
    if modality == "visual"
)

#: What is left when there is no microphone and nothing to trace on.
TAP_ONLY_TYPES = (str(ActivityType.SELECT_PICTURE), str(ActivityType.MATCH_PAIR))


def _evidence(**overrides: object) -> LearnerEvidence:
    """A neutral learner. Every scenario is this, with one thing changed."""
    base: dict[str, object] = {
        "skill": "colour_red",
        "modality": RECEPTIVE,
        "p_known": 0.7,
        "recent_results": ("correct", "correct"),
        "prompt_levels": ("independent", "independent"),
        "modality_accuracy": {},
        "available_activity_types": ALL_TYPES,
        "session_minutes": 3,
    }
    base.update(overrides)
    return LearnerEvidence(**base)  # type: ignore[arg-type]


def _decide(evidence: LearnerEvidence, candidates: Sequence[Candidate] = CANDIDATES):  # type: ignore[no-untyped-def]
    return decide(list(candidates), evidence).final


# ===========================================================================
# 1-6 — where the child is
# ===========================================================================


def test_1_a_complete_beginner_gets_the_easiest_most_supported_activity() -> None:
    decision = _decide(_evidence(p_known=0.15, recent_results=()))
    assert decision.difficulty == 1
    assert decision.support_level is SupportLevel.HIGH
    assert decision.demonstrate_first
    assert decision.activity_type == str(ActivityType.SELECT_PICTURE)


def test_2_an_advanced_learner_gets_the_hardest_least_supported_activity() -> None:
    decision = _decide(_evidence(p_known=0.95))
    assert decision.difficulty >= 3
    assert decision.support_level is SupportLevel.LOW
    assert decision.strategy is TeachingStrategy.INDEPENDENT_PRACTICE


def test_3_the_two_of_them_differ_on_every_axis_that_matters() -> None:
    """Stated as one assertion, because "different sessions" is the claim."""
    beginner = _decide(_evidence(p_known=0.15, recent_results=()))
    advanced = _decide(_evidence(p_known=0.95))
    assert beginner.difficulty != advanced.difficulty
    assert beginner.support_level is not advanced.support_level
    assert beginner.strategy is not advanced.strategy
    assert beginner.demonstrate_first != advanced.demonstrate_first


@pytest.mark.parametrize(("p_known", "expected"), [(0.62, 2), (0.70, 2), (0.80, 3), (0.92, 4)])
def test_4_difficulty_tracks_the_estimate_rather_than_being_one_of_two_values(
    p_known: float, expected: int
) -> None:
    assert _decide(_evidence(p_known=p_known)).difficulty == expected


def test_5_a_learner_just_over_the_struggling_line_is_not_treated_as_advanced() -> None:
    """The boundary. 0.6 is where support drops, and it should drop once."""
    below = _decide(_evidence(p_known=0.59))
    above = _decide(_evidence(p_known=0.61))
    assert below.support_level is SupportLevel.HIGH
    assert above.support_level is SupportLevel.LOW


def test_6_a_learner_with_no_history_at_all_still_gets_a_legal_decision() -> None:
    decision = _decide(_evidence(p_known=0.15, recent_results=(), prompt_levels=()))
    assert decision.next_skill in {candidate.skill_id for candidate in CANDIDATES}
    assert 1 <= decision.difficulty <= 5


# ===========================================================================
# 7-12 — what just happened
# ===========================================================================


def test_7_two_recent_failures_lower_the_difficulty_and_raise_the_support() -> None:
    steady = _decide(_evidence(p_known=0.8))
    failing = _decide(_evidence(p_known=0.8, recent_results=("correct", "incorrect", "incorrect")))
    assert failing.difficulty < steady.difficulty
    assert failing.support_level is SupportLevel.HIGH
    assert steady.support_level is SupportLevel.LOW


def test_8_recent_failure_switches_the_strategy_to_demonstrate_then_test() -> None:
    failing = _decide(_evidence(p_known=0.8, recent_results=("incorrect", "incorrect")))
    assert failing.strategy is TeachingStrategy.DEMONSTRATE_THEN_TEST
    assert failing.demonstrate_first
    assert "RECENT_ERRORS" in failing.reason_codes


def test_9_recent_failure_asks_for_the_skill_again_rather_than_moving_on() -> None:
    failing = _decide(_evidence(p_known=0.4, recent_results=("incorrect", "incorrect")))
    assert failing.repeat
    assert failing.action is BrainAction.REVIEW


def test_10_one_failure_after_a_run_of_successes_is_not_treated_as_a_pattern() -> None:
    """A single slip is a slip. `bkt.P_SLIP = 0.25` says so numerically; this
    says the teaching decision agrees."""
    decision = _decide(_evidence(p_known=0.85, recent_results=("correct", "correct", "incorrect")))
    assert decision.support_level is SupportLevel.LOW
    assert not decision.repeat


def test_11_random_looking_performance_is_treated_as_struggling() -> None:
    decision = _decide(
        _evidence(
            p_known=0.5,
            recent_results=("correct", "incorrect", "correct", "incorrect", "incorrect"),
        )
    )
    assert decision.support_level is SupportLevel.HIGH
    assert decision.difficulty == 1


def test_12_gradual_improvement_moves_the_decision_gradually() -> None:
    """Three points on one child's trajectory, in order."""
    early = _decide(_evidence(p_known=0.3, recent_results=("incorrect", "correct")))
    middle = _decide(_evidence(p_known=0.65))
    late = _decide(_evidence(p_known=0.93))
    assert early.difficulty <= middle.difficulty <= late.difficulty
    assert (early.support_level, middle.support_level, late.support_level) == (
        SupportLevel.HIGH,
        SupportLevel.LOW,
        SupportLevel.LOW,
    )


# ===========================================================================
# 13-17 — what works for this child
# ===========================================================================


def test_13_a_child_the_visual_record_favours_gets_a_visual_activity() -> None:
    decision = _decide(
        _evidence(modality_accuracy={"visual": 0.95, "audio": 0.30, "expressive": 0.20})
    )
    assert decision.activity_type in VISUAL_TYPES


def test_14_a_child_the_auditory_record_favours_gets_a_listening_activity() -> None:
    decision = _decide(
        _evidence(modality_accuracy={"visual": 0.30, "audio": 0.95, "expressive": 0.20})
    )
    assert decision.activity_type == str(ActivityType.LISTEN_CHOOSE)


def test_15_the_two_children_above_get_different_activities_from_the_same_state() -> None:
    """Same skill, same p_known, same history length. Only the modality record
    differs, and the session differs because of it."""
    visual = _decide(_evidence(modality_accuracy={"visual": 0.95, "audio": 0.3}))
    auditory = _decide(_evidence(modality_accuracy={"visual": 0.3, "audio": 0.95}))
    assert visual.activity_type != auditory.activity_type


def test_16_a_child_whose_speech_record_is_strong_is_asked_to_speak() -> None:
    decision = _decide(
        _evidence(
            modality_accuracy={"expressive": 0.95, "visual": 0.4, "audio": 0.4},
        )
    )
    assert decision.activity_type == str(ActivityType.SPEAK_WORD)


def test_17_demonstrations_that_have_worked_before_are_used_again() -> None:
    decision = _decide(_evidence(p_known=0.8, demonstration_accuracy=0.9))
    assert decision.demonstrate_first
    assert decision.strategy is TeachingStrategy.DEMONSTRATE_THEN_TEST


# ===========================================================================
# 18-22 — the session, and what the runtime can deliver
# ===========================================================================


def test_18_a_type_the_runtime_cannot_deliver_is_never_chosen() -> None:
    """A microphone nobody consented to, or a letter with no tracing guide."""
    decision = _decide(
        _evidence(
            available_activity_types=TAP_ONLY_TYPES,
            modality_accuracy={"expressive": 0.99, "productive": 0.99, "visual": 0.1},
        )
    )
    assert decision.activity_type in TAP_ONLY_TYPES


def test_19_the_type_just_used_is_not_used_again_when_there_is_a_choice() -> None:
    decision = _decide(
        _evidence(recent_activity_types=("match_pair",), modality_accuracy={"visual": 0.9})
    )
    assert decision.activity_type != "match_pair"


def test_20_a_tired_child_gets_the_easiest_activity_whatever_else_is_true() -> None:
    decision = _decide(_evidence(p_known=0.95, fatigue=True))
    assert decision.difficulty == 1
    assert decision.support_level is SupportLevel.HIGH
    assert decision.emotion == "calm"


def test_21_three_of_the_same_strategy_in_a_row_stops_the_repetition() -> None:
    decision = _decide(
        _evidence(
            p_known=0.3,
            recent_results=("incorrect", "incorrect"),
            recent_strategies=("demonstrate_then_test",) * 3,
        )
    )
    assert not decision.repeat


def test_22_a_new_skill_is_never_advanced_past() -> None:
    """`advance` on something the child has not met is a decision about nothing."""
    only_new = (
        Candidate(skill_id="colour_blue", modality=RECEPTIVE, kind=CandidateKind.NEW, priority=0),
    )
    result = decide(
        list(only_new),
        _evidence(skill="colour_blue", p_known=0.9),
        BrainDecision(
            next_skill="colour_blue",
            action=BrainAction.ADVANCE,
            difficulty=2,
            strategy=TeachingStrategy.INDEPENDENT_PRACTICE,
            modality=RECEPTIVE,
            support_level=SupportLevel.LOW,
            demonstrate_first=False,
            repeat=False,
            review_timing="none",
            activity_type=str(ActivityType.SELECT_PICTURE),
            theme="games",
            character="mano",
            behavior="encourage",
            emotion="encouraging",
            reason_codes=["MODEL_DECISION"],
        ),
    )
    assert result.final.action is BrainAction.CONTINUE
    assert "new_skill_cannot_advance" in result.actions


# ===========================================================================
# The property, stated directly
# ===========================================================================


def test_meaningfully_different_learners_get_meaningfully_different_decisions() -> None:
    """Six learners, six distinct decisions across the axes that matter.

    Not "some field differs somewhere" — the tuple of the five teaching controls
    has to be distinct for each, which is what "a different session" means when
    a caregiver is watching two children use the same product.
    """
    learners = {
        "beginner": _evidence(p_known=0.15, recent_results=()),
        "steady": _evidence(p_known=0.70),
        "strong-visual": _evidence(p_known=0.85, modality_accuracy={"visual": 0.95}),
        "strong-auditory": _evidence(p_known=0.85, modality_accuracy={"audio": 0.95}),
        "advanced-speaker": _evidence(p_known=0.96, modality_accuracy={"expressive": 0.95}),
        "advanced-but-tired": _evidence(
            p_known=0.96, modality_accuracy={"expressive": 0.95}, fatigue=True
        ),
    }
    signatures = {
        name: (
            decision.difficulty,
            str(decision.support_level),
            str(decision.strategy),
            decision.activity_type,
            decision.demonstrate_first,
        )
        for name, evidence in learners.items()
        for decision in (_decide(evidence),)
    }
    assert len(set(signatures.values())) == len(signatures), signatures


def test_a_beginner_and_a_struggling_learner_are_taught_the_same_way() -> None:
    """The complement, and it is not an oversight.

    Two children at different estimates who are both struggling get the same
    plainest-thing-first treatment, because that is what errorless learning
    says to do in both cases. Personalisation means the evidence decides — not
    that every child must get something different from every other child.
    """
    beginner = _decide(_evidence(p_known=0.15, recent_results=()))
    struggling = _decide(_evidence(p_known=0.45, recent_results=("incorrect", "incorrect")))
    assert beginner.difficulty == struggling.difficulty == 1
    assert beginner.support_level is struggling.support_level is SupportLevel.HIGH
    assert beginner.activity_type == struggling.activity_type


def test_identical_evidence_produces_an_identical_decision() -> None:
    """The other half: personalisation must not mean randomness.

    A caregiver reporting that something went wrong has to be able to have the
    same decision reproduced, and a child must not get a different session for
    pressing the button twice.
    """
    evidence = _evidence(p_known=0.72, modality_accuracy={"visual": 0.8, "audio": 0.6})
    first = _decide(evidence)
    second = _decide(evidence)
    assert first.model_dump() == second.model_dump()


def test_nothing_in_a_decision_can_carry_mastery() -> None:
    """Structural. `BrainDecision` has no field a mastery claim could ride in.

    Asserted rather than assumed, because the day someone adds
    `mastery_estimate: float` to this schema for a dashboard is the day the AI
    can set it.
    """
    forbidden = {
        "mastery",
        "mastered",
        "p_known",
        "score",
        "mastery_state",
        "is_mastered",
        "grade",
    }
    assert not (set(BrainDecision.model_fields) & forbidden)
