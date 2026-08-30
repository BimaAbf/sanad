"""The caregiver starting questionnaire, and what it may and may not derive.

The property that matters most is the negative one: there is no path from this
form to `mastered`. A parent's recollection of what their child can do is the
best information available before the child has done anything, and it is still
a recollection — so it sets a prior and it never sets a conclusion.
"""

from __future__ import annotations

import pytest

from app.modules.learning.domain.mastery import P_KNOWN_THRESHOLD, MasteryState
from app.modules.starting.domain.form import (
    AREA_CATEGORIES,
    BAND_LABEL_AR,
    BAND_ORDER,
    BAND_PRIOR,
    BAND_SKILL_COUNT,
    BAND_STATE,
    DURATION_OPTIONS,
    QUESTIONS,
    Area,
    Band,
    band_index,
    derive,
    is_complete,
    question_payload,
    remaining,
)


def _answers(band: str = "sometimes", duration: str = "medium") -> dict[str, str]:
    return {question.id: (duration if question.options else band) for question in QUESTIONS}


# ===========================================================================
# The form itself
# ===========================================================================


def test_every_one_of_the_ten_areas_the_specification_names_is_asked_about() -> None:
    asked = {question.area for question in QUESTIONS if question.area is not None}
    assert asked == set(Area)


def test_every_question_carries_a_concrete_example() -> None:
    """docs/04e §C12: parents cannot answer abstract questions about their own
    child reliably, and can answer concrete ones. The example is the question."""
    for question in QUESTIONS:
        assert question.prompt_ar.strip()
        assert question.example_ar.strip()


def test_every_band_has_caregiver_facing_arabic() -> None:
    for band in BAND_ORDER:
        assert BAND_LABEL_AR[band].strip()


def test_the_bands_are_ordered_and_the_order_is_the_scale() -> None:
    assert [band_index(band) for band in BAND_ORDER] == [0, 1, 2, 3]
    priors = [BAND_PRIOR[band] for band in BAND_ORDER]
    counts = [BAND_SKILL_COUNT[band] for band in BAND_ORDER]
    assert priors == sorted(priors)
    assert counts == sorted(counts)


def test_the_payload_carries_options_so_the_client_holds_no_copy() -> None:
    payload = question_payload()
    assert len(payload) == len(QUESTIONS)
    for item in payload:
        assert item["options"]
        for option in item["options"]:  # type: ignore[union-attr]
            assert option["label_ar"].strip()


def test_progress_only_ever_moves_forward() -> None:
    """docs/04b: a bar that goes backwards reads as the end receding."""
    answers: dict[str, str] = {}
    left = len(remaining(answers))
    for question in QUESTIONS:
        answers[question.id] = "sometimes" if question.uses_bands else "short"
        assert len(remaining(answers)) < left
        left = len(remaining(answers))
    assert is_complete(answers)
    assert remaining(answers) == ()


# ===========================================================================
# What it derives
# ===========================================================================


def test_the_top_band_cannot_reach_the_mastery_threshold() -> None:
    """The whole safety property, in one assertion.

    Even the strongest claim a caregiver can make about their child leaves the
    prior below `P_KNOWN_THRESHOLD`, so no seeded state can satisfy the mastery
    rule on the strength of the form alone.
    """
    assert BAND_PRIOR[Band.USUALLY] < P_KNOWN_THRESHOLD
    assert max(BAND_PRIOR.values()) < P_KNOWN_THRESHOLD


def test_no_band_seeds_a_state_that_claims_evidence_there_is_none_of() -> None:
    for band in BAND_ORDER:
        assert BAND_STATE[band] in (
            MasteryState.INTRODUCED.value,
            MasteryState.PRACTISING.value,
        )


def test_a_strong_answer_opens_more_skills_at_a_higher_prior_than_a_weak_one() -> None:
    weak = derive(_answers("not_yet"))
    strong = derive(_answers("usually"))
    assert len(strong.seeds) > len(weak.seeds)
    assert max(seed.prior for seed in strong.seeds) > max(seed.prior for seed in weak.seeds)


def test_two_different_forms_produce_two_different_profiles() -> None:
    """The claim the demo rests on, at the point it starts."""
    weak = derive({**_answers("not_yet"), "q_duration": "short"})
    strong = derive({**_answers("usually"), "q_duration": "long"})
    assert weak.effective_support != strong.effective_support
    assert weak.comfortable_minutes != strong.comfortable_minutes
    assert weak.area_bands != strong.area_bands


def test_the_areas_the_curriculum_has_no_skills_for_are_named_not_dropped() -> None:
    """`shapes` has no skills in the 88-skill curriculum. The answer is still
    stored; the gap is reported rather than papered over."""
    profile = derive(_answers())
    assert "shapes" in profile.unmapped_areas
    assert AREA_CATEGORIES[Area.SHAPES] == ()
    assert "shapes" in profile.area_bands


def test_a_partly_answered_form_still_produces_a_usable_profile() -> None:
    """A caregiver who skipped one question has not made the rest unusable."""
    answers = _answers()
    del answers["q_colors"]
    profile = derive(answers)
    assert profile.seeds
    assert "colors" in profile.area_bands


def test_an_answer_the_form_does_not_have_falls_back_to_the_middle() -> None:
    """Rather than raising. A profile that refuses to exist is worse for the
    child than one built from an odd answer."""
    profile = derive({**_answers(), "q_colors": "definitely-maybe"})
    assert profile.area_bands["colors"] == band_index(Band.STARTING)


def test_a_duration_the_form_does_not_have_falls_back_to_the_default() -> None:
    profile = derive({**_answers(), "q_duration": "forever"})
    assert profile.comfortable_minutes == 8


@pytest.mark.parametrize(("key", "minutes", "_label"), DURATION_OPTIONS)
def test_each_duration_option_maps_to_its_minutes(key: str, minutes: int, _label: str) -> None:
    assert derive({**_answers(), "q_duration": key}).comfortable_minutes == minutes


def test_a_caregiver_who_says_spoken_instructions_land_gets_an_auditory_start() -> None:
    audio = derive({**_answers(), "q_instructions": "usually"})
    visual = derive({**_answers(), "q_instructions": "not_yet"})
    assert audio.effective_modality == "audio"
    assert visual.effective_modality == "visual"
    assert audio.follows_spoken
    assert not visual.follows_spoken


def test_a_caregiver_who_says_demonstrations_help_gets_demonstrations() -> None:
    assert derive({**_answers(), "q_demonstration": "usually"}).demonstration_helps
    assert not derive({**_answers(), "q_demonstration": "not_yet"}).demonstration_helps


def test_needing_two_choices_keeps_the_support_level_off_the_floor() -> None:
    """A child who needs the field narrowed has a support need whatever the
    rest of the form said."""
    strong = _answers("usually")
    without = derive({**strong, "q_selection": "not_yet"})
    with_need = derive({**strong, "q_selection": "usually"})
    assert without.effective_support == "low"
    assert with_need.effective_support == "medium"


def test_an_empty_form_derives_a_neutral_profile_rather_than_failing() -> None:
    profile = derive({})
    assert profile.effective_support in ("low", "medium", "high")
    assert profile.comfortable_minutes == 8
    assert profile.seeds


def test_two_areas_mapping_to_one_category_do_not_cancel_each_other() -> None:
    """`simple_words` covers household AND body parts. Both get seeds."""
    profile = derive(_answers("usually"))
    categories = {seed.category for seed in profile.seeds}
    assert {"household", "body_parts"} <= categories


def test_the_derived_profile_serialises_everything_it_derived() -> None:
    """The stored `supports` column IS this, so a field missing here is a field
    a caregiver can never be shown the reason for."""
    profile = derive(_answers("usually", duration="long"))
    payload = profile.as_json()
    assert payload["effective_support"] == profile.effective_support
    assert payload["effective_modality"] == profile.effective_modality
    assert payload["comfortable_minutes"] == profile.comfortable_minutes
    assert payload["demonstration_helps"] is profile.demonstration_helps
    assert payload["follows_spoken"] is profile.follows_spoken
    assert payload["comfortable_speaking"] is profile.comfortable_speaking
    assert payload["area_bands"] == profile.area_bands
    assert payload["unmapped_areas"] == list(profile.unmapped_areas)
