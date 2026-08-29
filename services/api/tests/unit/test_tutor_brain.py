from __future__ import annotations

from app.modules.learning.domain.candidates import Candidate, CandidateKind
from app.modules.tutor_ai.brain import (
    BrainAction,
    BrainDecision,
    LearnerEvidence,
    TeachingStrategy,
    build_request,
    decide,
)

CANDIDATES = [
    Candidate("counting", "receptive", CandidateKind.DUE, 0),
    Candidate("colors", "visual", CandidateKind.CONFIDENCE, 1),
]


def test_struggling_learner_gets_visual_demonstration_and_review() -> None:
    result = decide(
        CANDIDATES,
        LearnerEvidence(
            skill="counting",
            modality="receptive",
            p_known=0.42,
            recent_results=("incorrect", "incorrect"),
            modality_accuracy={"visual": 0.85, "audio": 0.45},
            demonstration_accuracy=0.9,
            retries=3,
            fatigue=False,
        ),
    )
    assert result.final.action is BrainAction.REVIEW
    assert result.final.strategy is TeachingStrategy.DEMONSTRATE_THEN_TEST
    assert result.final.modality == "visual"
    assert result.final.repeat is True


def test_advanced_learner_gets_independent_practice() -> None:
    result = decide(
        CANDIDATES,
        LearnerEvidence(
            skill="colors",
            modality="visual",
            p_known=0.92,
            recent_results=("correct", "correct", "correct"),
            modality_accuracy={"visual": 0.9},
            retention=0.9,
        ),
    )
    assert result.final.action is BrainAction.CONTINUE
    assert result.final.strategy is TeachingStrategy.INDEPENDENT_PRACTICE
    assert result.final.support_level.value == "low"


def test_unsafe_model_skill_falls_back_to_candidate() -> None:
    proposed = BrainDecision(
        next_skill="not-in-curriculum",
        action=BrainAction.ADVANCE,
        difficulty=5,
        strategy=TeachingStrategy.INDEPENDENT_PRACTICE,
        modality="visual",
        support_level="low",
        demonstrate_first=False,
        repeat=False,
        review_timing="none",
        activity_type="unsafe_activity",
        theme="anything",
        character="mano",
        behavior="encourage",
        emotion="encouraging",
        reason_codes=["MODEL_DECISION"],
    )
    result = decide(CANDIDATES, LearnerEvidence("counting", "receptive", 0.4), proposed)
    assert result.final.next_skill == "counting"
    assert result.actions == ("unsupported_skill",)


def test_new_skill_proposal_cannot_advance() -> None:
    # Regression: with use_enum_values=True the `is BrainAction.ADVANCE`
    # guard was dead code and this safety check never fired.
    new_candidate = [
        Candidate("shapes", "visual", CandidateKind.NEW, 0),
        Candidate("counting", "receptive", CandidateKind.DUE, 1),
    ]
    proposed = BrainDecision(
        next_skill="shapes",
        action=BrainAction.ADVANCE,
        difficulty=2,
        strategy=TeachingStrategy.INDEPENDENT_PRACTICE,
        modality="visual",
        support_level="low",
        demonstrate_first=False,
        repeat=False,
        review_timing="none",
        activity_type="listen_point",
        theme="games",
        character="mano",
        behavior="encourage",
        emotion="encouraging",
        reason_codes=["MODEL_DECISION"],
    )
    result = decide(new_candidate, LearnerEvidence("shapes", "visual", 0.7), proposed)
    assert result.final.action is BrainAction.CONTINUE
    assert "new_skill_cannot_advance" in result.actions


def test_fatigue_caps_difficulty_and_supports_child() -> None:
    proposed = BrainDecision(
        next_skill="counting",
        action=BrainAction.CONTINUE,
        difficulty=4,
        strategy=TeachingStrategy.INDEPENDENT_PRACTICE,
        modality="receptive",
        support_level="low",
        demonstrate_first=False,
        repeat=True,
        review_timing="immediate",
        activity_type="listen_point",
        theme="games",
        character="kira",
        behavior="encourage",
        emotion="encouraging",
        reason_codes=["MODEL_DECISION"],
    )
    result = decide(
        CANDIDATES, LearnerEvidence("counting", "receptive", 0.7, fatigue=True), proposed
    )
    assert result.final.difficulty == 1
    assert result.final.support_level.value == "high"
    assert "fatigue_difficulty_capped" in result.actions


def test_request_contains_evidence_without_identity() -> None:
    request = build_request(CANDIDATES, LearnerEvidence("counting", "receptive", 0.5))
    assert request["learner_evidence"]["p_known"] == 0.5
    assert "display_name" not in str(request)
