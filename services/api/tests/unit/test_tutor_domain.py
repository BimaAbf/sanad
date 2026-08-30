"""The tutor's pure domain: contract, builder, evaluator, guardrails, rewards.

The single most important group here is `TestEvaluation`. Every other test in
the repository can pass while the browser decides whether a child was right;
these are the ones that say it does not, by showing that the verdict is a
function of the stored answer key and the response, and of nothing else.
"""

from __future__ import annotations

import datetime as dt
from typing import ClassVar

import pytest
from seeds.tracing import reference_path, traceable_skills

from app.modules.tutor.domain import rewards as rewards_domain
from app.modules.tutor.domain.build import SkillRow, build, choice_count_for, numeral_value
from app.modules.tutor.domain.contract import (
    EXPECTED_RESPONSE,
    MODALITY_OF,
    SUPPORTED_CATEGORIES,
    TEACHING_MODALITY,
    ActivityType,
    AnswerKey,
    supports,
)
from app.modules.tutor.domain.evaluate import (
    MIN_SPEECH_CONFIDENCE,
    NextAction,
    Outcome,
    ResponseInvalidError,
    SupportAction,
    evaluate,
)
from app.modules.tutor.domain.guardrails import (
    MAX_ACTIVITIES_PER_SESSION,
    GuardContext,
    SessionLimitReachedError,
    enforce,
    floor_prompt_level,
)
from app.modules.tutor.domain.report import (
    AttemptFact,
    MasteryChange,
    best_streak,
    compute,
    narrative_violations,
    resolve_narrative,
)
from app.modules.tutor_ai.brain import (
    BrainAction,
    BrainDecision,
    SupportLevel,
    TeachingStrategy,
)

NOW = dt.datetime(2026, 3, 1, 10, 0, tzinfo=dt.UTC)


def _skill(code: str, category: str, order: int = 1) -> SkillRow:
    return SkillRow(
        skill_id=f"id-{code}",
        code=code,
        category=category,
        label_ar=f"ar-{code}",
        label_egy=f"egy-{code}",
        alt_text_ar=f"alt-{code}",
        intro_order=order,
    )


COLOURS = [
    _skill(f"color_{n}", "colors", i)
    for i, n in enumerate(["red", "blue", "yellow", "green", "white"])
]
NUMBERS = [_skill(f"num_{n}", "numbers", i) for i, n in enumerate(["1", "2", "3", "4"])]
HOUSEHOLD = [_skill(f"hh_{n}", "household", i) for i, n in enumerate(["cup", "plate"])]


def _build(activity_type: ActivityType, target: SkillRow, pool: list[SkillRow], **kwargs):  # type: ignore[no-untyped-def]
    options: dict[str, object] = {
        "difficulty": 2,
        "modality": MODALITY_OF[activity_type],
        "strategy": "independent_practice",
        "support_level": "low",
        "prompt_level": "independent",
        "demonstrate_first": False,
        "max_choices": 4,
        "seed": 7,
    }
    options.update(kwargs)
    return build(activity_type=activity_type, target=target, pool=pool, **options)  # type: ignore[arg-type]


# ===========================================================================
# The contract
# ===========================================================================


class TestContract:
    def test_every_activity_type_declares_everything_the_runtime_asks_of_it(self) -> None:
        """A type in the enum with no entry in a table is a blank screen."""
        for activity_type in ActivityType:
            assert activity_type in EXPECTED_RESPONSE
            assert activity_type in MODALITY_OF
            assert activity_type in SUPPORTED_CATEGORIES
            assert activity_type in TEACHING_MODALITY
            assert SUPPORTED_CATEGORIES[activity_type], activity_type

    def test_selection_works_for_every_category_because_it_is_the_fallback(self) -> None:
        for category in ("letters", "numbers", "colors", "body_parts", "household", "social"):
            assert supports(ActivityType.SELECT_PICTURE, category)

    def test_sorting_is_not_offered_for_letters_or_numbers(self) -> None:
        """ "Is أ a letter or a colour" is a question about the filing system."""
        assert not supports(ActivityType.SORT_CATEGORY, "letters")
        assert not supports(ActivityType.SORT_CATEGORY, "numbers")

    def test_the_answer_key_round_trips_through_json(self) -> None:
        key = AnswerKey(
            option_id="opt-2",
            count=3,
            assignments={"opt-0": "colors"},
            order=("opt-1", "opt-0"),
            target_label_ar="أحمر",
            competing_labels=("أزرق",),
            reference_path=(((0.1, 0.2), (0.3, 0.4)),),
            pass_threshold=0.62,
        )
        assert AnswerKey.from_json(key.as_json()) == key


# ===========================================================================
# The builder
# ===========================================================================


class TestBuilder:
    @pytest.mark.parametrize("activity_type", list(ActivityType))
    def test_no_presentation_ever_contains_the_answer(self, activity_type: ActivityType) -> None:
        """The property the whole architecture rests on, checked per type.

        Serialised and searched rather than field-by-field: a future field that
        happens to carry the answer would pass a field-by-field check written
        before it existed.
        """
        import json

        target = {
            ActivityType.COUNT_OBJECTS: NUMBERS[2],
            ActivityType.ORDER_SEQUENCE: NUMBERS[1],
            ActivityType.TRACE_LETTER: _skill("num_1", "numbers", 0),
            ActivityType.SORT_CATEGORY: COLOURS[0],
        }.get(activity_type, COLOURS[0])
        pool = {
            ActivityType.COUNT_OBJECTS: NUMBERS,
            ActivityType.ORDER_SEQUENCE: NUMBERS,
            ActivityType.SORT_CATEGORY: [*COLOURS[1:], *HOUSEHOLD],
        }.get(activity_type, COLOURS[1:])

        activity = _build(activity_type, target, pool)
        rendered = json.dumps(activity.presentation.as_json(), ensure_ascii=False)
        assert '"correct"' not in rendered
        assert "answer" not in rendered
        # And the key is not derivable from the option ordering either: for the
        # types with options, the right one is not always first.
        if activity.answer_key.option_id:
            assert activity.answer_key.option_id in rendered

    def test_the_same_seed_builds_the_same_activity_twice(self) -> None:
        first = _build(ActivityType.SELECT_PICTURE, COLOURS[0], COLOURS[1:], seed=42)
        second = _build(ActivityType.SELECT_PICTURE, COLOURS[0], COLOURS[1:], seed=42)
        assert first.presentation.as_json() == second.presentation.as_json()
        assert first.answer_key == second.answer_key

    def test_a_different_seed_arranges_the_cards_differently(self) -> None:
        """Otherwise "the answer is always on the left" is a strategy."""
        arrangements = {
            tuple(
                option.skill_code
                for option in _build(
                    ActivityType.SELECT_PICTURE, COLOURS[0], COLOURS[1:], seed=seed
                ).presentation.options
            )
            for seed in range(12)
        }
        assert len(arrangements) > 1

    def test_the_child_choice_limit_beats_the_difficulty(self) -> None:
        """An accessibility setting is not a difficulty knob."""
        assert choice_count_for(5, max_choices=2) == 2
        assert choice_count_for(5, max_choices=4) == 4
        assert choice_count_for(1, max_choices=4) == 2
        # Never below two: a one-choice activity is not a discrimination, and
        # `bkt.guess_probability` floors at two for the same reason.
        assert choice_count_for(1, max_choices=1) == 2

    def test_a_demonstration_line_appears_only_when_it_was_asked_for(self) -> None:
        with_demo = _build(
            ActivityType.SELECT_PICTURE, COLOURS[0], COLOURS[1:], demonstrate_first=True
        )
        without = _build(ActivityType.SELECT_PICTURE, COLOURS[0], COLOURS[1:])
        assert with_demo.presentation.demonstration_ar
        assert not without.presentation.demonstration_ar

    def test_a_listening_activity_hides_the_written_labels(self) -> None:
        """A listening task with the words on the cards is a reading task."""
        listening = _build(ActivityType.LISTEN_CHOOSE, COLOURS[0], COLOURS[1:])
        pointing = _build(ActivityType.SELECT_PICTURE, COLOURS[0], COLOURS[1:])
        assert listening.presentation.hide_labels
        assert not pointing.presentation.hide_labels

    def test_counting_puts_the_right_number_of_objects_on_screen(self) -> None:
        activity = _build(ActivityType.COUNT_OBJECTS, NUMBERS[2], NUMBERS)
        assert activity.presentation.object_count == 3
        assert activity.answer_key.count == 3

    def test_numeral_value_reads_the_code_and_refuses_anything_else(self) -> None:
        assert numeral_value("num_7") == 7
        assert numeral_value("color_red") == 0

    def test_a_sequence_is_presented_out_of_order(self) -> None:
        activity = _build(ActivityType.ORDER_SEQUENCE, NUMBERS[1], NUMBERS)
        presented = [option.option_id for option in activity.presentation.options]
        assert sorted(presented) == sorted(activity.answer_key.order)
        assert len(activity.answer_key.order) >= 2

    def test_sorting_needs_a_card_from_another_category_and_says_so(self) -> None:
        with pytest.raises(ValueError, match="another category"):
            _build(ActivityType.SORT_CATEGORY, COLOURS[0], COLOURS[1:])

    def test_speaking_carries_every_other_taught_word_as_a_competitor(self) -> None:
        """docs/adr/011 §1: an ASR hypothesis matching a DIFFERENT taught word
        must not be accepted as this one."""
        activity = _build(ActivityType.SPEAK_WORD, COLOURS[0], COLOURS[1:])
        assert set(activity.answer_key.competing_labels) == {row.label_ar for row in COLOURS[1:]}

    def test_tracing_refuses_a_skill_with_no_reference_path(self) -> None:
        with pytest.raises(ValueError, match="no tracing reference"):
            _build(ActivityType.TRACE_LETTER, _skill("letter_qaf", "letters"), [])

    def test_tracing_carries_the_guide_and_the_threshold(self) -> None:
        code = traceable_skills()[0]
        activity = _build(ActivityType.TRACE_LETTER, _skill(code, "letters"), [])
        assert activity.answer_key.reference_path == reference_path(code)
        assert activity.answer_key.pass_threshold > 0
        # The child is shown the guide — that is what tracing IS.
        assert activity.presentation.reference_path == activity.answer_key.reference_path


# ===========================================================================
# The evaluator — the authoritative verdict
# ===========================================================================


class TestEvaluation:
    def _choice_activity(self):  # type: ignore[no-untyped-def]
        return _build(ActivityType.SELECT_PICTURE, COLOURS[0], COLOURS[1:])

    def test_the_right_option_is_correct_and_the_wrong_one_is_not(self) -> None:
        activity = self._choice_activity()
        right = activity.answer_key.option_id
        wrong = next(
            option.option_id
            for option in activity.presentation.options
            if option.option_id != right
        )
        good = evaluate(
            activity_type=ActivityType.SELECT_PICTURE,
            answer_key=activity.answer_key,
            presentation=activity.presentation.as_json(),
            response={"kind": "choice", "option_id": right},
        )
        bad = evaluate(
            activity_type=ActivityType.SELECT_PICTURE,
            answer_key=activity.answer_key,
            presentation=activity.presentation.as_json(),
            response={"kind": "choice", "option_id": wrong},
        )
        assert good.correct and good.outcome is Outcome.CORRECT
        assert not bad.correct and bad.outcome is Outcome.INCORRECT
        assert bad.next_action is NextAction.RETRY
        assert bad.support_action is SupportAction.DEMONSTRATE

    def test_a_wrong_answer_records_what_the_child_actually_chose(self) -> None:
        """A confusion pattern is not computable from a session total."""
        activity = self._choice_activity()
        wrong = next(
            option
            for option in activity.presentation.options
            if option.option_id != activity.answer_key.option_id
        )
        result = evaluate(
            activity_type=ActivityType.SELECT_PICTURE,
            answer_key=activity.answer_key,
            presentation=activity.presentation.as_json(),
            response={"kind": "choice", "option_id": wrong.option_id},
        )
        assert result.selected_skill_code == wrong.skill_code

    def test_a_right_answer_records_no_confusion(self) -> None:
        activity = self._choice_activity()
        result = evaluate(
            activity_type=ActivityType.SELECT_PICTURE,
            answer_key=activity.answer_key,
            presentation=activity.presentation.as_json(),
            response={"kind": "choice", "option_id": activity.answer_key.option_id},
        )
        assert result.selected_skill_code is None

    def test_an_option_that_was_never_offered_is_refused_not_marked_wrong(self) -> None:
        """A malformed response is a client defect. Recording it as a wrong
        answer would put a defect in a child's clinical record."""
        activity = self._choice_activity()
        with pytest.raises(ResponseInvalidError):
            evaluate(
                activity_type=ActivityType.SELECT_PICTURE,
                answer_key=activity.answer_key,
                presentation=activity.presentation.as_json(),
                response={"kind": "choice", "option_id": "opt-99"},
            )

    def test_a_response_of_the_wrong_shape_is_refused(self) -> None:
        activity = self._choice_activity()
        with pytest.raises(ResponseInvalidError, match="expects a choice"):
            evaluate(
                activity_type=ActivityType.SELECT_PICTURE,
                answer_key=activity.answer_key,
                presentation=activity.presentation.as_json(),
                response={"kind": "count", "value": 3},
            )

    def test_no_response_is_recorded_and_is_never_a_wrong_answer(self) -> None:
        activity = self._choice_activity()
        result = evaluate(
            activity_type=ActivityType.SELECT_PICTURE,
            answer_key=activity.answer_key,
            presentation=activity.presentation.as_json(),
            response={"kind": "no_response"},
        )
        assert result.outcome is Outcome.NO_RESPONSE
        assert result.attempt_result == "no_response"
        assert not result.correct

    def test_counting_compares_the_number_and_nothing_else(self) -> None:
        activity = _build(ActivityType.COUNT_OBJECTS, NUMBERS[2], NUMBERS)
        for value, expected in ((3, True), (2, False), (0, False)):
            result = evaluate(
                activity_type=ActivityType.COUNT_OBJECTS,
                answer_key=activity.answer_key,
                presentation=activity.presentation.as_json(),
                response={"kind": "count", "value": value},
            )
            assert result.correct is expected

    def test_sorting_is_correct_only_when_every_card_is_placed_correctly(self) -> None:
        activity = _build(ActivityType.SORT_CATEGORY, COLOURS[0], [*COLOURS[1:], *HOUSEHOLD])
        right = dict(activity.answer_key.assignments)
        result = evaluate(
            activity_type=ActivityType.SORT_CATEGORY,
            answer_key=activity.answer_key,
            presentation=activity.presentation.as_json(),
            response={"kind": "sort", "assignments": right},
        )
        assert result.correct

        swapped = dict(right)
        first = next(iter(swapped))
        swapped[first] = "household" if swapped[first] != "household" else "colors"
        wrong = evaluate(
            activity_type=ActivityType.SORT_CATEGORY,
            answer_key=activity.answer_key,
            presentation=activity.presentation.as_json(),
            response={"kind": "sort", "assignments": swapped},
        )
        assert not wrong.correct
        assert wrong.detail["misplaced"] == 1

    def test_a_sorting_response_that_leaves_a_card_unplaced_is_refused(self) -> None:
        activity = _build(ActivityType.SORT_CATEGORY, COLOURS[0], [*COLOURS[1:], *HOUSEHOLD])
        partial = dict(list(activity.answer_key.assignments.items())[:1])
        with pytest.raises(ResponseInvalidError, match="every card"):
            evaluate(
                activity_type=ActivityType.SORT_CATEGORY,
                answer_key=activity.answer_key,
                presentation=activity.presentation.as_json(),
                response={"kind": "sort", "assignments": partial},
            )

    def test_a_sequence_is_correct_only_in_the_right_order(self) -> None:
        activity = _build(ActivityType.ORDER_SEQUENCE, NUMBERS[1], NUMBERS)
        right = list(activity.answer_key.order)
        assert evaluate(
            activity_type=ActivityType.ORDER_SEQUENCE,
            answer_key=activity.answer_key,
            presentation=activity.presentation.as_json(),
            response={"kind": "sequence", "order": right},
        ).correct
        assert not evaluate(
            activity_type=ActivityType.ORDER_SEQUENCE,
            answer_key=activity.answer_key,
            presentation=activity.presentation.as_json(),
            response={"kind": "sequence", "order": list(reversed(right))},
        ).correct

    # --- speech ------------------------------------------------------------

    def _speech_activity(self):  # type: ignore[no-untyped-def]
        return _build(ActivityType.SPEAK_WORD, COLOURS[0], COLOURS[1:])

    def _speak(self, **response: object):  # type: ignore[no-untyped-def]
        activity = self._speech_activity()
        return evaluate(
            activity_type=ActivityType.SPEAK_WORD,
            answer_key=activity.answer_key,
            presentation=activity.presentation.as_json(),
            response={"kind": "speech", **response},
        )

    def test_the_expected_word_said_clearly_is_accepted(self) -> None:
        result = self._speak(transcript=COLOURS[0].label_ar, confidence=0.9)
        assert result.correct
        assert result.outcome is Outcome.CORRECT

    def test_low_confidence_is_uncertainty_and_never_a_wrong_answer(self) -> None:
        """The rule the specification states in capitals, as a test.

        A microphone that could not hear a child has not established that the
        child was wrong, and recording `incorrect` would put that on file.
        """
        result = self._speak(
            transcript=COLOURS[0].label_ar, confidence=MIN_SPEECH_CONFIDENCE - 0.01
        )
        assert result.outcome is Outcome.UNCERTAIN
        assert result.attempt_result == "no_response"
        assert result.support_action is SupportAction.CAREGIVER_CONFIRM

    def test_a_missing_recogniser_is_uncertainty_and_the_session_continues(self) -> None:
        result = self._speak(transcript="", confidence=0.0, recogniser_available=False)
        assert result.outcome is Outcome.UNCERTAIN
        assert result.detail["reason"] == "recogniser_unavailable"
        assert result.next_action is NextAction.SUPPORT

    def test_the_caregiver_is_believed_over_the_recogniser(self) -> None:
        """They were in the room. A model trained on adult speech was not."""
        result = self._speak(
            transcript="something else entirely", confidence=0.99, caregiver_confirmed=True
        )
        assert result.correct
        assert result.attempt_result == "caregiver_confirmed"
        assert result.detail["source"] == "caregiver"

    def test_a_confidently_heard_different_word_is_not_accepted(self) -> None:
        result = self._speak(transcript=COLOURS[1].label_ar, confidence=0.95)
        assert not result.correct

    # --- drawing -----------------------------------------------------------

    def _tracing(self):  # type: ignore[no-untyped-def]
        code = traceable_skills()[0]
        return _build(ActivityType.TRACE_LETTER, _skill(code, "letters"), []), code

    def test_a_faithful_trace_passes_and_a_blank_canvas_does_not(self) -> None:
        activity, code = self._tracing()
        from app.modules.tutor.domain.drawing import resample

        points = resample([[(x, y) for x, y in s] for s in reference_path(code)])
        good = evaluate(
            activity_type=ActivityType.TRACE_LETTER,
            answer_key=activity.answer_key,
            presentation=activity.presentation.as_json(),
            response={
                "kind": "strokes",
                "strokes": [[[x * 400, y * 400] for x, y in points]],
                "width": 400,
                "height": 400,
            },
        )
        blank = evaluate(
            activity_type=ActivityType.TRACE_LETTER,
            answer_key=activity.answer_key,
            presentation=activity.presentation.as_json(),
            response={"kind": "strokes", "strokes": [], "width": 400, "height": 400},
        )
        assert good.correct and good.score is not None and good.threshold is not None
        assert not blank.correct
        assert blank.support_action is SupportAction.DEMONSTRATE

    def test_a_tracing_response_without_a_canvas_size_is_refused(self) -> None:
        """Without it there is nothing to normalise by, and a score computed
        from raw pixels would mean a different thing on every device."""
        activity, _code = self._tracing()
        with pytest.raises(ResponseInvalidError, match="canvas size"):
            evaluate(
                activity_type=ActivityType.TRACE_LETTER,
                answer_key=activity.answer_key,
                presentation=activity.presentation.as_json(),
                response={"kind": "strokes", "strokes": [[[1, 1], [2, 2]]]},
            )


# ===========================================================================
# The guardrails
# ===========================================================================


def _decision(**overrides: object) -> BrainDecision:
    payload: dict[str, object] = {
        "next_skill": "color_red",
        "action": BrainAction.CONTINUE,
        "difficulty": 2,
        "strategy": TeachingStrategy.INDEPENDENT_PRACTICE,
        "modality": "visual",
        "support_level": SupportLevel.LOW,
        "demonstrate_first": False,
        "repeat": False,
        "review_timing": "none",
        "activity_type": "select_picture",
        "theme": "games",
        "character": "mano",
        "behavior": "encourage",
        "emotion": "encouraging",
        "reason_codes": ["MODEL_DECISION"],
    }
    payload.update(overrides)
    return BrainDecision(**payload)  # type: ignore[arg-type]


class TestGuardrails:
    CONTEXT = GuardContext(categories={"color_red": "colors"}, traceable=frozenset())

    def test_an_activity_type_that_does_not_exist_becomes_selection(self) -> None:
        result = enforce(_decision(activity_type="teleport"), self.CONTEXT)
        assert result.activity_type is ActivityType.SELECT_PICTURE
        assert "unknown_activity_type" in result.actions

    def test_a_type_the_category_cannot_support_becomes_selection(self) -> None:
        result = enforce(_decision(activity_type="count_objects"), self.CONTEXT)
        assert result.activity_type is ActivityType.SELECT_PICTURE
        assert "activity_type_unsupported_for_category" in result.actions

    def test_speaking_without_consent_becomes_selection(self) -> None:
        context = GuardContext(categories={"color_red": "colors"}, microphone_allowed=False)
        result = enforce(_decision(activity_type="speak_word"), context)
        assert result.activity_type is ActivityType.SELECT_PICTURE
        assert "microphone_unavailable" in result.actions

    def test_tracing_a_skill_with_no_guide_becomes_selection(self) -> None:
        context = GuardContext(
            categories={"letter_qaf": "letters"}, traceable=frozenset({"letter_baa"})
        )
        result = enforce(_decision(next_skill="letter_qaf", activity_type="trace_letter"), context)
        assert result.activity_type is ActivityType.SELECT_PICTURE
        assert "no_tracing_reference" in result.actions

    def test_a_difficulty_jump_of_four_is_capped_to_one(self) -> None:
        context = GuardContext(categories={"color_red": "colors"}, previous_difficulty=1)
        result = enforce(_decision(difficulty=5), context)
        assert result.difficulty == 2
        assert "difficulty_jump_capped" in result.actions

    def test_a_difficulty_collapse_is_capped_the_same_way(self) -> None:
        context = GuardContext(categories={"color_red": "colors"}, previous_difficulty=5)
        result = enforce(_decision(difficulty=1), context)
        assert result.difficulty == 4
        assert "difficulty_drop_capped" in result.actions

    def test_an_unmet_prerequisite_is_refused_outright(self) -> None:
        """Repaired nowhere: teaching a child something they have no foundation
        for is not a decision that can be corrected into a good one."""
        context = GuardContext(
            categories={"num_5": "numbers"},
            prerequisites={"num_5": ("num_1",)},
            mastered=frozenset(),
        )
        with pytest.raises(SessionLimitReachedError, match="unmet prerequisites"):
            enforce(_decision(next_skill="num_5"), context)

    def test_a_met_prerequisite_lets_the_decision_through(self) -> None:
        context = GuardContext(
            categories={"num_5": "numbers"},
            prerequisites={"num_5": ("num_1",)},
            mastered=frozenset({"num_1"}),
        )
        assert enforce(_decision(next_skill="num_5"), context).activity_type

    def test_the_session_limit_stops_the_session_rather_than_the_activity(self) -> None:
        context = GuardContext(
            categories={"color_red": "colors"},
            activities_done=MAX_ACTIVITIES_PER_SESSION,
        )
        result = enforce(_decision(), context)
        assert result.session_exhausted
        assert "session_limit_reached" in result.actions

    def test_the_same_skill_three_times_running_stops_repeating(self) -> None:
        context = GuardContext(
            categories={"color_red": "colors"},
            recent_skills=("color_red", "color_red", "color_red"),
        )
        result = enforce(_decision(repeat=True), context)
        assert not result.repeat
        assert "consecutive_repetition_bounded" in result.actions

    def test_the_hardest_activity_is_never_offered_with_the_least_help(self) -> None:
        context = GuardContext(categories={"color_red": "colors"}, previous_difficulty=4)
        result = enforce(_decision(difficulty=4, support_level=SupportLevel.LOW), context)
        assert result.support_level == "medium"
        assert "support_raised_for_difficulty" in result.actions

    def test_a_clean_decision_is_left_alone(self) -> None:
        """A guardrail that fires on every decision tells you nothing."""
        result = enforce(_decision(), self.CONTEXT)
        assert result.actions == ()


class TestPromptFloor:
    def test_a_demonstrated_activity_cannot_come_back_as_independent(self) -> None:
        """The specification's rule that a full demonstration must not prove
        independent mastery, at the one place a client could claim otherwise."""
        assert (
            floor_prompt_level("independent", demonstrate_first=True, support_level="low")
            == "gestural"
        )

    def test_high_support_floors_the_level_further(self) -> None:
        assert (
            floor_prompt_level("independent", demonstrate_first=True, support_level="high")
            == "partial_verbal"
        )

    def test_an_unsupported_activity_leaves_an_independent_answer_alone(self) -> None:
        assert (
            floor_prompt_level("independent", demonstrate_first=False, support_level="low")
            == "independent"
        )

    def test_the_floor_never_lowers_what_the_client_reported(self) -> None:
        """A client saying "I showed them the answer" is always believed."""
        assert (
            floor_prompt_level("full_model", demonstrate_first=False, support_level="low")
            == "full_model"
        )

    def test_an_unknown_level_is_treated_as_the_weakest_claim(self) -> None:
        assert (
            floor_prompt_level("nonsense", demonstrate_first=True, support_level="high")
            == "partial_verbal"
        )


# ===========================================================================
# Rewards
# ===========================================================================


class TestRewards:
    def test_an_independent_correct_answer_is_worth_more_than_a_prompted_one(self) -> None:
        independent = rewards_domain.stars_for_attempt(result="correct", prompt_level="independent")
        prompted = rewards_domain.stars_for_attempt(result="correct", prompt_level="gestural")
        assert independent > prompted > 0

    def test_a_wrong_answer_earns_nothing(self) -> None:
        for result in ("incorrect", "no_response"):
            assert rewards_domain.stars_for_attempt(result=result, prompt_level="independent") == 0
            assert (
                rewards_domain.attempt_reward(
                    result=result, prompt_level="independent", attempt_key="k1"
                )
                is None
            )

    def test_being_given_the_answer_earns_nothing_however_it_is_recorded(self) -> None:
        """Otherwise the fastest route to a full sticker chart is to wait for
        the prompt ladder to answer for you."""
        for result in ("correct", "accepted_on_effort", "caregiver_confirmed"):
            assert rewards_domain.stars_for_attempt(result=result, prompt_level="full_model") == 0

    def test_effort_and_a_caregiver_confirmation_are_both_worth_something(self) -> None:
        for result in ("accepted_on_effort", "caregiver_confirmed"):
            assert (
                rewards_domain.stars_for_attempt(result=result, prompt_level="independent")
                == rewards_domain.STARS_SUPPORTED_CORRECT
            )

    def test_a_reward_is_keyed_on_the_attempt_that_earned_it(self) -> None:
        """Which is what makes a retried POST create no second star."""
        first = rewards_domain.attempt_reward(
            result="correct", prompt_level="independent", attempt_key="abc"
        )
        second = rewards_domain.attempt_reward(
            result="correct", prompt_level="independent", attempt_key="abc"
        )
        assert first is not None and second is not None
        assert first.idempotency_key == second.idempotency_key == "attempt:abc"

    def test_the_completion_bonus_is_keyed_on_the_session(self) -> None:
        bonus = rewards_domain.session_reward(session_id="s1", activities_done=4)
        assert bonus is not None
        assert bonus.idempotency_key == "session_complete:s1"

    def test_a_session_with_nothing_in_it_earns_no_completion_bonus(self) -> None:
        assert rewards_domain.session_reward(session_id="s1", activities_done=0) is None

    def test_every_achievement_has_caregiver_facing_arabic(self) -> None:
        for achievement in rewards_domain.Achievement:
            assert rewards_domain.ACHIEVEMENT_LABEL_AR[achievement].strip()

    def test_achievements_report_what_is_true_not_what_is_new(self) -> None:
        context = rewards_domain.AchievementContext(
            completed_sessions=3,
            distinct_session_days=4,
            best_streak_this_session=6,
            accepted_speech_attempts=1,
            passed_tracings=1,
            skills_mastered=2,
        )
        earned = rewards_domain.achievements_earned(context)
        assert set(earned) == set(rewards_domain.Achievement)
        assert rewards_domain.achievements_earned(context) == earned

    def test_nothing_is_earned_by_a_child_who_has_done_nothing(self) -> None:
        assert rewards_domain.achievements_earned(rewards_domain.AchievementContext()) == ()

    def test_a_streak_of_four_does_not_unlock_the_five_in_a_row_achievement(self) -> None:
        context = rewards_domain.AchievementContext(best_streak_this_session=4)
        assert rewards_domain.Achievement.FIVE_IN_A_ROW not in (
            rewards_domain.achievements_earned(context)
        )


# ===========================================================================
# The session report
# ===========================================================================


def _fact(skill: str, result: str, prompt_level: str = "independent") -> AttemptFact:
    return AttemptFact(
        skill_code=skill,
        skill_label_ar=f"ar-{skill}",
        activity_type="select_picture",
        result=result,
        prompt_level=prompt_level,
        latency_ms=2000,
        at=NOW,
    )


class TestReport:
    ATTEMPTS: ClassVar[list[AttemptFact]] = [
        _fact("color_red", "correct"),
        _fact("color_red", "incorrect"),
        _fact("color_blue", "correct", "gestural"),
        _fact("color_blue", "correct"),
        _fact("num_1", "no_response"),
    ]

    def test_the_totals_add_up(self) -> None:
        facts = compute(self.ATTEMPTS, duration_minutes=7)
        assert facts.activities_completed == 5
        assert facts.correct == 3
        assert facts.incorrect == 1
        assert facts.no_response == 1
        assert facts.correct + facts.incorrect + facts.no_response == 5

    def test_independent_and_supported_successes_are_counted_apart(self) -> None:
        facts = compute(self.ATTEMPTS)
        assert facts.independent_responses == 2
        assert facts.supported_responses == 1
        assert facts.independent_responses + facts.supported_responses == facts.correct

    def test_skills_are_listed_in_the_order_the_child_met_them(self) -> None:
        facts = compute(self.ATTEMPTS)
        assert facts.skills_practised == ("color_red", "color_blue", "num_1")

    def test_the_two_caregiver_lists_partition_the_skills(self) -> None:
        facts = compute(self.ATTEMPTS)
        assert facts.went_well == ("ar-color_blue",)
        assert set(facts.needs_practice) == {"ar-color_red", "ar-num_1"}

    def test_the_streak_is_the_longest_run_of_successes(self) -> None:
        assert best_streak(self.ATTEMPTS) == 2
        assert best_streak([]) == 0
        assert best_streak([_fact("a", "correct")] * 6) == 6

    def test_a_narrative_may_not_contain_a_number_the_session_did_not_produce(self) -> None:
        facts = compute(self.ATTEMPTS, duration_minutes=7)
        problems = narrative_violations("لعبنا 12 لعبة.\nشغل حلو.", facts)
        assert any("12" in problem for problem in problems)

    def test_arabic_indic_digits_are_checked_too(self) -> None:
        """Otherwise a fabricated number passes by being written differently."""
        facts = compute(self.ATTEMPTS, duration_minutes=7)
        assert narrative_violations("لعبنا ١٢ لعبة.\nشغل حلو.", facts)

    def test_a_narrative_that_restates_the_facts_is_allowed_through(self) -> None:
        facts = compute(self.ATTEMPTS, duration_minutes=7)
        narrative, source, problems = resolve_narrative(
            ai_narrative="لعبنا 5 ألعاب.\nجاوب لوحده 2 مرات.", facts=facts
        )
        assert problems == []
        assert source == "ai"
        assert "5" in narrative

    def test_no_narrative_at_all_ships_the_template(self) -> None:
        facts = compute(self.ATTEMPTS, duration_minutes=7)
        narrative, source, _problems = resolve_narrative(ai_narrative=None, facts=facts)
        assert source == "template"
        assert str(facts.activities_completed) in narrative

    def test_a_rejected_narrative_ships_the_template_and_says_why(self) -> None:
        facts = compute(self.ATTEMPTS, duration_minutes=7)
        narrative, source, problems = resolve_narrative(
            ai_narrative="طفلك عمل 99 حاجة.\nشغل حلو.", facts=facts
        )
        assert source == "template"
        assert problems
        assert "99" not in narrative

    def test_mastery_changes_are_carried_through_untouched(self) -> None:
        change = MasteryChange(
            skill_code="color_red",
            skill_label_ar="أحمر",
            from_state="introduced",
            to_state="practising",
        )
        facts = compute(self.ATTEMPTS, mastery_changes=[change])
        assert facts.mastery_changes == (change,)
        assert facts.as_json()["mastery_changes"][0]["to_state"] == "practising"

    def test_an_empty_session_computes_without_dividing_by_zero(self) -> None:
        facts = compute([])
        assert facts.activities_completed == 0
        assert facts.median_latency_ms is None
        assert facts.went_well == ()


# ===========================================================================
# The refusals — every malformed response, named
# ===========================================================================


class TestMalformedResponses:
    """A malformed response is a client defect, and never a wrong answer.

    Each of these would otherwise be recorded against a child as `incorrect`,
    which is the difference between a bug report and a line in a clinical
    record.
    """

    def _for(self, activity_type: ActivityType):  # type: ignore[no-untyped-def]
        target = {
            ActivityType.COUNT_OBJECTS: NUMBERS[2],
            ActivityType.ORDER_SEQUENCE: NUMBERS[1],
            ActivityType.SORT_CATEGORY: COLOURS[0],
        }.get(activity_type, COLOURS[0])
        pool = {
            ActivityType.COUNT_OBJECTS: NUMBERS,
            ActivityType.ORDER_SEQUENCE: NUMBERS,
            ActivityType.SORT_CATEGORY: [*COLOURS[1:], *HOUSEHOLD],
        }.get(activity_type, COLOURS[1:])
        activity = _build(activity_type, target, pool)
        return activity

    def _evaluate(self, activity_type: ActivityType, response: dict[str, object]):  # type: ignore[no-untyped-def]
        activity = self._for(activity_type)
        return evaluate(
            activity_type=activity_type,
            answer_key=activity.answer_key,
            presentation=activity.presentation.as_json(),
            response=response,
        )

    def test_a_choice_with_no_option_id_is_refused(self) -> None:
        with pytest.raises(ResponseInvalidError, match="option_id"):
            self._evaluate(ActivityType.SELECT_PICTURE, {"kind": "choice"})

    def test_a_count_with_no_value_is_refused(self) -> None:
        with pytest.raises(ResponseInvalidError, match="integer value"):
            self._evaluate(ActivityType.COUNT_OBJECTS, {"kind": "count"})

    def test_a_count_that_is_not_a_number_is_refused(self) -> None:
        with pytest.raises(ResponseInvalidError, match="integer value"):
            self._evaluate(ActivityType.COUNT_OBJECTS, {"kind": "count", "value": "تلاتة"})

    def test_a_sort_with_no_assignments_is_refused(self) -> None:
        with pytest.raises(ResponseInvalidError, match="assignment per card"):
            self._evaluate(ActivityType.SORT_CATEGORY, {"kind": "sort", "assignments": {}})

    def test_a_sort_that_is_not_a_mapping_is_refused(self) -> None:
        with pytest.raises(ResponseInvalidError, match="assignment per card"):
            self._evaluate(ActivityType.SORT_CATEGORY, {"kind": "sort", "assignments": ["opt-0"]})

    def test_a_sequence_with_no_order_is_refused(self) -> None:
        with pytest.raises(ResponseInvalidError, match="ordered option ids"):
            self._evaluate(ActivityType.ORDER_SEQUENCE, {"kind": "sequence", "order": []})

    def test_a_sequence_that_is_not_a_list_is_refused(self) -> None:
        with pytest.raises(ResponseInvalidError, match="ordered option ids"):
            self._evaluate(ActivityType.ORDER_SEQUENCE, {"kind": "sequence", "order": "opt-0"})

    def test_a_sequence_using_an_option_twice_is_refused(self) -> None:
        activity = self._for(ActivityType.ORDER_SEQUENCE)
        first = activity.answer_key.order[0]
        with pytest.raises(ResponseInvalidError, match="every option exactly once"):
            evaluate(
                activity_type=ActivityType.ORDER_SEQUENCE,
                answer_key=activity.answer_key,
                presentation=activity.presentation.as_json(),
                response={"kind": "sequence", "order": [first] * len(activity.answer_key.order)},
            )

    def test_strokes_that_are_not_a_list_are_refused(self) -> None:
        code = traceable_skills()[0]
        activity = _build(ActivityType.TRACE_LETTER, _skill(code, "letters"), [])
        with pytest.raises(ResponseInvalidError, match="list of strokes"):
            evaluate(
                activity_type=ActivityType.TRACE_LETTER,
                answer_key=activity.answer_key,
                presentation=activity.presentation.as_json(),
                response={"kind": "strokes", "strokes": "nope", "width": 400, "height": 400},
            )


def test_a_sequence_needs_at_least_two_items_to_order() -> None:
    """A one-item sequence is not a sequence, and the builder says so rather
    than shipping a screen with one card and a done button."""
    with pytest.raises(ValueError, match="at least two items"):
        _build(ActivityType.ORDER_SEQUENCE, NUMBERS[0], [])


def test_a_speech_attempt_that_is_nothing_like_the_word_is_unclear() -> None:
    """The third band. Below `RETRY_THRESHOLD` the scorer is not saying the
    child was wrong — it is saying it has no idea what it heard."""
    activity = _build(ActivityType.SPEAK_WORD, COLOURS[0], COLOURS[1:])
    result = evaluate(
        activity_type=ActivityType.SPEAK_WORD,
        answer_key=activity.answer_key,
        presentation=activity.presentation.as_json(),
        response={"kind": "speech", "transcript": "كتكوت مشمش", "confidence": 0.95},
    )
    assert result.outcome is Outcome.UNCERTAIN
    assert result.support_action is SupportAction.CAREGIVER_CONFIRM
    assert result.attempt_result == "no_response"


def test_a_transcript_with_no_confidence_estimate_is_still_scored() -> None:
    """Firefox and Safari report no confidence. Treating that as a low one
    would make every attempt on those browsers uncertain."""
    activity = _build(ActivityType.SPEAK_WORD, COLOURS[0], COLOURS[1:])
    result = evaluate(
        activity_type=ActivityType.SPEAK_WORD,
        answer_key=activity.answer_key,
        presentation=activity.presentation.as_json(),
        response={"kind": "speech", "transcript": COLOURS[0].label_ar, "confidence": 0},
    )
    assert result.correct
    assert result.detail["confidence_reported"] is False


def test_a_narrative_of_one_line_is_rejected() -> None:
    """Four lines is what docs/04c asks for; one is a fragment, six is a page."""
    facts = compute([_fact("color_red", "correct")], duration_minutes=3)
    assert narrative_violations("شغل حلو.", facts)
    assert narrative_violations("\n".join(["سطر"] * 6), facts)


def test_resampling_skips_an_empty_stroke_and_a_zero_length_segment() -> None:
    """Both arrive from real hardware: a pointer-down with no move, and two
    samples reported at the same coordinate."""
    from app.modules.tutor.domain.drawing import resample

    points = resample([[], [(0.0, 0.0), (0.0, 0.0), (0.5, 0.0)]])
    assert points
    assert points[0] == (0.0, 0.0)
    assert points[-1][0] <= 0.5
