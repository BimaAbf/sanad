"""Authoritative response evaluation. The frontend does not decide correctness.

One function, `evaluate`, takes the activity as it was DELIVERED (from the
database, including the answer key the client was never sent) and the response
the child produced, and returns the outcome. There is no other path by which a
response becomes a result.

That is a structural claim, not a convention, and it rests on three things:

  * the answer key lives in a column the serialiser never touches, so a client
    cannot post its own;
  * `Outcome.correct` is computed here and returned to the client, which
    renders it — the client has no branch that decides;
  * every activity type is handled in this one `match`, so a new type that
    forgets to say what "correct" means fails to compile rather than defaulting
    to true.

**Uncertainty is a third state, not a wrong answer.** A speech attempt the
recogniser could not make out is `UNCERTAIN`, which asks the child to try again
or the caregiver to confirm. Scoring it `incorrect` would put a child's
pronunciation on file as wrong on the strength of a microphone.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.modules.tutor.domain.contract import (
    EXPECTED_RESPONSE,
    ActivityType,
    AnswerKey,
    ResponseKind,
)
from app.modules.tutor.domain.drawing import DrawingResult, evaluate_drawing
from app.modules.voice.domain.scoring import (
    AsrResult,
    ExpectedWord,
    Hypothesis,
    Verdict,
    caregiver_override,
    score_attempt,
)


class Outcome(StrEnum):
    """What the backend concluded. `attempts.result` is derived from this."""

    CORRECT = "correct"
    INCORRECT = "incorrect"
    #: A real attempt the system cannot grade — a speech attempt with nothing
    #: usable in it, chiefly. Never recorded as a wrong answer.
    UNCERTAIN = "uncertain"
    #: The child did not answer at all before the ladder ran out.
    NO_RESPONSE = "no_response"


class NextAction(StrEnum):
    NEXT = "next"
    RETRY = "retry"
    #: Retry, with the support level raised first.
    SUPPORT = "support"


class SupportAction(StrEnum):
    NONE = "none"
    DEMONSTRATE = "demonstrate"
    #: Ask the caregiver to say whether the child got it right. Only ever for
    #: speech, and only when the recogniser could not decide.
    CAREGIVER_CONFIRM = "caregiver_confirm"
    SIMPLIFY = "simplify"


#: `attempts.result`, per outcome. `accepted_on_effort` and
#: `caregiver_confirmed` come out of the speech path and are set there.
ATTEMPT_RESULT: dict[Outcome, str] = {
    Outcome.CORRECT: "correct",
    Outcome.INCORRECT: "incorrect",
    Outcome.UNCERTAIN: "no_response",
    Outcome.NO_RESPONSE: "no_response",
}

#: A speech hypothesis below this confidence is not treated as what the child
#: said. It is treated as the microphone not having heard them, which is a
#: different thing and leads to a different screen.
#:
#: It applies ONLY when a confidence was actually reported. Browsers differ:
#: Chrome returns a number, and others return zero or nothing at all for a
#: perfectly good transcript. Treating an absent estimate as a low one would
#: make every attempt on those browsers "uncertain", so an unreported
#: confidence falls through to the pronunciation scorer — which is the real
#: evidence about what the child said, and the thing this product actually
#: has an opinion about.
MIN_SPEECH_CONFIDENCE = 0.35


class ResponseInvalidError(ValueError):
    """The response is not the shape this activity type asked for."""


@dataclass(frozen=True, slots=True)
class Evaluation:
    outcome: Outcome
    correct: bool
    attempt_result: str
    next_action: NextAction
    support_action: SupportAction
    #: What the child selected, when it was a wrong option — this is what makes
    #: a confusion pattern computable later.
    selected_skill_code: str | None = None
    #: Type-specific numbers the caregiver console and the inspector show.
    detail: dict[str, Any] = field(default_factory=dict)
    #: Drawing and speech carry a score against a threshold.
    score: float | None = None
    threshold: float | None = None


def _choice(
    response: Mapping[str, Any], key: AnswerKey, options: Sequence[Mapping[str, Any]]
) -> tuple[bool, str | None]:
    chosen = str(response.get("option_id", ""))
    if not chosen:
        raise ResponseInvalidError("a choice response must name an option_id")
    known = {str(option.get("option_id")) for option in options}
    if chosen not in known:
        raise ResponseInvalidError("that option is not part of this activity")
    correct = chosen == key.option_id
    selected = next(
        (
            str(option.get("skill_code"))
            for option in options
            if str(option.get("option_id")) == chosen
        ),
        None,
    )
    return correct, (None if correct else selected)


def _speech(response: Mapping[str, Any], key: AnswerKey, *, attempt_no: int) -> Evaluation:
    """The speech ladder: caregiver confirmation, then ASR, then uncertainty.

    The caregiver's confirmation is checked FIRST and is final. They were in the
    room; a recogniser trained on adult speech was not. docs/04d prices a
    confirmed attempt below an independent one, and `caregiver_override()` is
    the function that already encodes that.
    """
    if bool(response.get("caregiver_confirmed")):
        score = caregiver_override()
        return Evaluation(
            outcome=Outcome.CORRECT,
            correct=True,
            attempt_result="caregiver_confirmed",
            next_action=NextAction.NEXT,
            support_action=SupportAction.NONE,
            detail={"source": "caregiver", "similarity": round(score.similarity, 3)},
            score=score.similarity,
        )

    transcript = str(response.get("transcript", "")).strip()
    raw_confidence = response.get("confidence")
    # "Reported" means the client sent a positive number. A zero from a browser
    # that does not estimate confidence is an absence, not a measurement.
    reported = isinstance(raw_confidence, int | float) and float(raw_confidence) > 0.0
    confidence = float(raw_confidence or 0.0)
    recogniser_available = bool(response.get("recogniser_available", True))

    if (
        not recogniser_available
        or not transcript
        or (reported and confidence < MIN_SPEECH_CONFIDENCE)
    ):
        # LOW CONFIDENCE IS NOT A WRONG ANSWER. The child said something and we
        # could not hear it; the caregiver button is already on screen and the
        # activity stays open.
        return Evaluation(
            outcome=Outcome.UNCERTAIN,
            correct=False,
            attempt_result="no_response",
            next_action=NextAction.SUPPORT,
            support_action=SupportAction.CAREGIVER_CONFIRM,
            detail={
                "source": "asr",
                "reason": (
                    "recogniser_unavailable"
                    if not recogniser_available
                    else ("nothing_heard" if not transcript else "low_confidence")
                ),
                "confidence": round(confidence, 3),
                "confidence_reported": reported,
            },
        )

    scored = score_attempt(
        ExpectedWord(
            skill_code=key.option_id or "",
            label_ar=key.target_label_ar,
            label_egy=key.target_label_egy or key.target_label_ar,
            phonemes=key.target_phonemes,
        ),
        AsrResult(n_best=(Hypothesis(text=transcript, confidence=confidence),), provider="client"),
        attempt_no=attempt_no,
        competing_labels=key.competing_labels,
    )

    detail = {
        "source": "asr",
        "heard": scored.heard,
        "similarity": round(scored.similarity, 3),
        "verdict": scored.verdict.value,
        "reason": scored.reason,
        "confidence": round(confidence, 3),
        "confidence_reported": reported,
    }
    if scored.verdict is Verdict.ACCEPT:
        return Evaluation(
            outcome=Outcome.CORRECT,
            correct=True,
            attempt_result=(scored.result.value if scored.result else "correct"),
            next_action=NextAction.NEXT,
            support_action=SupportAction.NONE,
            detail=detail,
            score=scored.similarity,
        )
    if scored.verdict is Verdict.RETRY:
        return Evaluation(
            outcome=Outcome.INCORRECT,
            correct=False,
            attempt_result="incorrect",
            next_action=NextAction.RETRY,
            support_action=SupportAction.DEMONSTRATE,
            detail=detail,
            score=scored.similarity,
        )
    return Evaluation(
        outcome=Outcome.UNCERTAIN,
        correct=False,
        attempt_result="no_response",
        next_action=NextAction.SUPPORT,
        support_action=SupportAction.CAREGIVER_CONFIRM,
        detail=detail,
        score=scored.similarity,
    )


def _strokes(response: Mapping[str, Any], key: AnswerKey) -> Evaluation:
    raw = response.get("strokes")
    if not isinstance(raw, list):
        raise ResponseInvalidError("a tracing response must carry a list of strokes")
    strokes = [
        [(float(point[0]), float(point[1])) for point in stroke]
        for stroke in raw
        if isinstance(stroke, list)
    ]
    width = float(response.get("width", 0) or 0)
    height = float(response.get("height", 0) or 0)
    if width <= 0 or height <= 0:
        raise ResponseInvalidError("a tracing response must carry the canvas size it was drawn on")

    result: DrawingResult = evaluate_drawing(
        strokes,
        key.reference_path,
        width=width,
        height=height,
        threshold=key.pass_threshold,
    )
    detail = {"source": "drawing", **result.metrics.as_json()}
    if result.passed:
        return Evaluation(
            outcome=Outcome.CORRECT,
            correct=True,
            attempt_result="correct",
            next_action=NextAction.NEXT,
            support_action=SupportAction.NONE,
            detail=detail,
            score=result.score,
            threshold=result.threshold,
        )
    return Evaluation(
        outcome=Outcome.INCORRECT,
        correct=False,
        attempt_result="incorrect",
        next_action=NextAction.RETRY,
        # A blank or near-blank canvas needs a demonstration; a real attempt
        # that missed needs another go at the same thing.
        support_action=(
            SupportAction.DEMONSTRATE
            if result.metrics.rejected or result.metrics.coverage < 0.3
            else SupportAction.NONE
        ),
        detail=detail,
        score=result.score,
        threshold=result.threshold,
    )


def evaluate(
    *,
    activity_type: ActivityType,
    answer_key: AnswerKey,
    presentation: Mapping[str, Any],
    response: Mapping[str, Any],
    attempt_no: int = 1,
) -> Evaluation:
    """The one place a child's response becomes a result.

    `presentation` is passed because two types need to check the response
    against what was actually on screen — an option id that was never offered
    is a malformed response, not a wrong answer.
    """
    kind = str(response.get("kind", ""))
    if kind == ResponseKind.NO_RESPONSE:
        # The prompt ladder ran out. Recorded, never shown, and never a star:
        # the child engaged and we know nothing about what they know.
        return Evaluation(
            outcome=Outcome.NO_RESPONSE,
            correct=False,
            attempt_result="no_response",
            next_action=NextAction.SUPPORT,
            support_action=SupportAction.DEMONSTRATE,
        )

    expected = EXPECTED_RESPONSE[activity_type]
    if kind != expected:
        raise ResponseInvalidError(f"{activity_type} expects a {expected} response, not {kind!r}")

    options = list(presentation.get("options", []))

    match activity_type:
        case ActivityType.SELECT_PICTURE | ActivityType.LISTEN_CHOOSE | ActivityType.MATCH_PAIR:
            correct, selected = _choice(response, answer_key, options)
            return _plain(correct, selected)

        case ActivityType.COUNT_OBJECTS:
            try:
                value = int(response["value"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ResponseInvalidError(
                    "a counting response must carry an integer value"
                ) from exc
            # No confusion code: a counting response is a number, not a card,
            # so there is no "what did they pick instead" to record.
            return _plain(
                value == answer_key.count,
                None,
                detail={"answered": value, "expected": answer_key.count},
            )

        case ActivityType.SORT_CATEGORY:
            given = response.get("assignments")
            if not isinstance(given, dict) or not given:
                raise ResponseInvalidError("a sorting response must carry an assignment per card")
            normalised = {str(k): str(v) for k, v in given.items()}
            if set(normalised) != set(answer_key.assignments):
                raise ResponseInvalidError("a sorting response must place every card exactly once")
            wrong = [
                option_id
                for option_id, bin_id in normalised.items()
                if answer_key.assignments[option_id] != bin_id
            ]
            return _plain(not wrong, None, detail={"misplaced": len(wrong)})

        case ActivityType.ORDER_SEQUENCE:
            given_order = response.get("order")
            if not isinstance(given_order, list) or not given_order:
                raise ResponseInvalidError("a sequence response must carry the ordered option ids")
            order = tuple(str(value) for value in given_order)
            if sorted(order) != sorted(answer_key.order):
                raise ResponseInvalidError("a sequence response must use every option exactly once")
            correct = order == answer_key.order
            return _plain(
                correct,
                None,
                detail={
                    "in_place": sum(
                        1 for a, b in zip(order, answer_key.order, strict=True) if a == b
                    ),
                    "length": len(answer_key.order),
                },
            )

        case ActivityType.SPEAK_WORD:
            return _speech(response, answer_key, attempt_no=attempt_no)

        # `case _` and not `case ActivityType.TRACE_LETTER`, for the last arm
        # only. `ActivityType` is exhaustive, so a named final arm leaves the
        # match with a fall-through path that no input can reach — an untakeable
        # branch, which the 100%-branch gate on `domain/` correctly refuses to
        # let stand. A catch-all is identical in behaviour and honest about
        # there being nothing after it.
        case _:
            return _strokes(response, answer_key)


def _plain(
    correct: bool,
    selected_skill_code: str | None,
    *,
    detail: dict[str, Any] | None = None,
) -> Evaluation:
    """The shared shape for the types whose answer is simply right or wrong."""
    return Evaluation(
        outcome=Outcome.CORRECT if correct else Outcome.INCORRECT,
        correct=correct,
        attempt_result="correct" if correct else "incorrect",
        next_action=NextAction.NEXT if correct else NextAction.RETRY,
        support_action=SupportAction.NONE if correct else SupportAction.DEMONSTRATE,
        selected_skill_code=selected_skill_code,
        detail=detail or {},
    )


__all__ = [
    "ATTEMPT_RESULT",
    "MIN_SPEECH_CONFIDENCE",
    "Evaluation",
    "NextAction",
    "Outcome",
    "ResponseInvalidError",
    "SupportAction",
    "evaluate",
]
