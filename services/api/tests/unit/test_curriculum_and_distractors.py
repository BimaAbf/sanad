"""P06 data-quality and distractor-selection tests.

The acceptance criteria say "assert with a data-quality test, not a manual
check" — so every structural claim about the curriculum is asserted here rather
than trusted.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter

import pytest
from seeds.curriculum import (
    ACTIVITY_TEMPLATES,
    MIN_DISTRACTORS,
    PLACEHOLDER,
    REVIEWED_BY,
    Skill,
    build_skills,
)

from app.modules.content.domain.distractors import (
    MIN_COLOUR_DISTANCE,
    DistractorSkill,
    choose_distractors,
    colour_distance,
    visual_distance,
)
from app.modules.content.domain.manifest import (
    MAX_INSTRUCTION_WORDS,
    ActivityEntry,
    ChildSettings,
    ChoiceEntry,
    build_manifest,
    build_prompt_ladder,
    instruction_word_count,
    missing_media,
    validate,
)

SKILLS = build_skills()
BY_CODE = {s.code: s for s in SKILLS}


def _as_distractor(skill: Skill) -> DistractorSkill:
    return DistractorSkill(
        code=skill.code,
        category=skill.category,
        label_ar=skill.label_ar,
        # Real phonemes are a placeholder; use the code's first letter so the
        # initial-phoneme rule has something distinguishing to work on.
        phonemes=skill.code.split("_", 1)[-1],
        difficulty_tier=skill.difficulty_tier,
        colour=skill.colour,
    )


DISTRACTORS = [_as_distractor(s) for s in SKILLS]


# --- curriculum shape -------------------------------------------------------


def test_there_are_exactly_88_skills() -> None:
    assert len(SKILLS) == 88


def test_category_counts_match_the_specification() -> None:
    """docs/02 §10.1, exactly."""
    assert Counter(s.category for s in SKILLS) == {
        "letters": 28,
        "numbers": 10,
        "colors": 10,
        "body_parts": 10,
        "household": 20,
        "social": 10,
    }


def test_every_skill_has_the_mandatory_fields() -> None:
    for skill in SKILLS:
        assert skill.code, skill
        assert skill.label_ar.strip(), skill.code
        assert skill.label_vowelised.strip(), skill.code
        assert skill.label_egy.strip(), skill.code
        assert skill.phonemes.strip(), skill.code
        assert skill.alt_text_ar.strip(), skill.code
        assert 1 <= skill.difficulty_tier <= 5, skill.code


def test_every_skill_has_at_least_four_distractor_candidates() -> None:
    """P06 acceptance criterion."""
    for skill in SKILLS:
        assert len(skill.distractor_pool) >= MIN_DISTRACTORS, skill.code


def test_a_distractor_pool_never_contains_its_own_skill() -> None:
    for skill in SKILLS:
        assert skill.code not in skill.distractor_pool, skill.code


def test_every_distractor_code_resolves_to_a_real_skill() -> None:
    for skill in SKILLS:
        for code in skill.distractor_pool:
            assert code in BY_CODE, f"{skill.code} -> {code}"


def test_codes_and_intro_order_are_unique() -> None:
    assert len({s.code for s in SKILLS}) == len(SKILLS)
    assert len({s.intro_order for s in SKILLS}) == len(SKILLS)


def test_arabic_labels_are_actually_arabic() -> None:
    """A latin-only label would mean a transcription slipped through."""
    for skill in SKILLS:
        if skill.category == "numbers":
            continue  # numerals are Arabic-Indic digits
        assert any("؀" <= ch <= "ۿ" for ch in skill.label_ar), skill.code


def test_all_ten_colours_carry_perceptual_coordinates() -> None:
    """The tier-1 contrast rule cannot run without them."""
    colours = [s for s in SKILLS if s.category == "colors"]
    assert len(colours) == 10
    for skill in colours:
        assert skill.colour is not None, skill.code


def test_non_colour_skills_have_no_colour_coordinates() -> None:
    for skill in SKILLS:
        if skill.category != "colors":
            assert skill.colour is None, skill.code


# --- the review gate --------------------------------------------------------


def test_the_curriculum_is_not_yet_signed_off() -> None:
    """P06 requires a REVIEWED-BY header that CI checks is non-empty.

    This test asserts the CURRENT, HONEST state: nobody has reviewed it. When a
    native Egyptian Arabic speaker signs off, REVIEWED_BY gets their name and
    this test is inverted to `assert REVIEWED_BY` — that inversion is the
    deliberate, visible moment the gate closes.

    Until then, nothing in this file may be shown to a family.
    """
    assert REVIEWED_BY == "", (
        "REVIEWED_BY is now set. Invert this test to `assert REVIEWED_BY` and "
        "remove the placeholder markers that the reviewer has replaced."
    )


def test_unreviewed_fields_are_visibly_marked() -> None:
    """A placeholder must look like one, so it cannot ship by accident."""
    for skill in SKILLS:
        assert PLACEHOLDER in skill.phonemes, skill.code
        assert PLACEHOLDER in skill.transliteration, skill.code
        assert PLACEHOLDER in skill.alt_text_ar, skill.code


# --- activity templates -----------------------------------------------------


def test_there_are_nine_activity_templates() -> None:
    assert len(ACTIVITY_TEMPLATES) == 9
    assert len({t.code for t in ACTIVITY_TEMPLATES}) == 9


def test_the_documented_template_codes_are_all_present() -> None:
    assert {t.code for t in ACTIVITY_TEMPLATES} == {
        "listen_point_2choice",
        "listen_point_3choice",
        "listen_point_4choice",
        "match_pair_picture",
        "match_pair_word",
        "say_it_word",
        "say_it_repeat_after",
        "sort_category_2bin",
        "story_moment_3frame",
    }


def test_every_instruction_is_five_words_or_fewer_for_every_skill() -> None:
    """P06: assert for EVERY template x EVERY skill, not a sample.

    docs/06 §4: instructions are <= 5 words, spoken and written and illustrated.
    A longer instruction is a working-memory load this population cannot carry.
    """
    for template in ACTIVITY_TEMPLATES:
        for skill in SKILLS:
            words = instruction_word_count(template.instruction_ar, skill.label_egy)
            assert words <= MAX_INSTRUCTION_WORDS, (
                f"{template.code} x {skill.code}: {words} words -- "
                f"{template.instruction_ar.replace('{label}', skill.label_egy)!r}"
            )


def test_every_template_has_success_and_retry_audio() -> None:
    for template in ACTIVITY_TEMPLATES:
        assert template.success_audio_pool
        assert template.retry_audio_pool


def test_retry_lines_are_never_corrective() -> None:
    """There is no failure state in this product, so no line may name one."""
    banned = ("غلط", "خطأ", "لأ مش", "فشل")
    for template in ACTIVITY_TEMPLATES:
        for line in template.retry_audio_pool:
            for word in banned:
                assert word not in line, f"{template.code}: {line!r} contains {word!r}"


def test_choice_counts_are_within_the_supported_range() -> None:
    for template in ACTIVITY_TEMPLATES:
        assert 1 <= template.choice_count <= 4, template.code


# --- distractor selection ---------------------------------------------------


def _colour(code: str) -> DistractorSkill:
    return _as_distractor(BY_CODE[code])


def test_a_red_card_never_sits_beside_an_orange_card_at_tier_1() -> None:
    """The rule docs/04c §C05 states in exactly these words."""
    red = _colour("color_red")
    for tier in (1, 2):
        chosen = choose_distractors(red, DISTRACTORS, count=3, tier=tier)
        assert "color_orange" not in {c.code for c in chosen}


def test_tier_1_never_offers_a_distractor_from_the_same_category() -> None:
    for skill in DISTRACTORS[:20]:
        chosen = choose_distractors(skill, DISTRACTORS, count=3, tier=1)
        for candidate in chosen:
            assert candidate.category != skill.category, (
                f"{skill.code} got same-category distractor {candidate.code}"
            )


def test_no_colour_pair_within_the_threshold_is_ever_offered_at_tier_1() -> None:
    """P06: assert over ALL colour skills, not a sample."""
    colours = [d for d in DISTRACTORS if d.category == "colors"]
    for target in colours:
        chosen = choose_distractors(target, DISTRACTORS, count=4, tier=1)
        for candidate in chosen:
            assert colour_distance(candidate, target) > MIN_COLOUR_DISTANCE, (
                f"{target.code} vs {candidate.code}: "
                f"distance {colour_distance(candidate, target):.3f}"
            )


def test_tier_1_avoids_a_shared_initial_phoneme() -> None:
    target = _colour("color_red")
    chosen = choose_distractors(target, DISTRACTORS, count=4, tier=1)
    for candidate in chosen:
        assert candidate.phonemes[:1] != target.phonemes[:1]


def test_tier_3_introduces_near_misses_but_only_among_mastered_skills() -> None:
    target = _colour("color_red")
    mastered = frozenset({"color_orange", "color_pink"})
    chosen = choose_distractors(target, DISTRACTORS, count=2, tier=3, mastered=mastered)
    assert {c.code for c in chosen} <= mastered


def test_tier_3_falls_back_to_the_wider_pool_when_nothing_is_mastered() -> None:
    """A child with no mastered skills must still get a playable activity."""
    target = _colour("color_red")
    chosen = choose_distractors(target, DISTRACTORS, count=2, tier=3, mastered=frozenset())
    assert len(chosen) == 2


def test_a_distractor_used_recently_is_not_reused() -> None:
    target = _colour("color_red")
    first = choose_distractors(target, DISTRACTORS, count=2, tier=1)
    recent = [c.code for c in first]
    second = choose_distractors(target, DISTRACTORS, count=2, tier=1, recent=recent)
    assert not (set(recent) & {c.code for c in second})


def test_recency_yields_rather_than_leaving_an_activity_with_no_wrong_answer() -> None:
    """A stale distractor beats a broken activity."""
    target = _colour("color_red")
    everything = [d.code for d in DISTRACTORS]
    chosen = choose_distractors(target, DISTRACTORS, count=2, tier=1, recent=everything)
    assert len(chosen) == 2


def test_an_inactive_skill_is_never_offered() -> None:
    target = _colour("color_red")
    pool = [
        DistractorSkill(
            code=d.code,
            category=d.category,
            label_ar=d.label_ar,
            phonemes=d.phonemes,
            difficulty_tier=d.difficulty_tier,
            colour=d.colour,
            is_active=False,
        )
        for d in DISTRACTORS
    ]
    assert choose_distractors(target, pool, count=3, tier=1) == []


def test_the_target_is_never_its_own_distractor() -> None:
    for tier in (1, 3):
        for target in DISTRACTORS[:20]:
            chosen = choose_distractors(target, DISTRACTORS, count=4, tier=tier)
            assert target.code not in {c.code for c in chosen}


def test_selection_returns_fewer_rather_than_relaxing_the_contrast_rules() -> None:
    """A short activity is a content problem; a bad distractor harms a child."""
    target = _colour("color_red")
    tiny_pool = [target, _colour("color_orange")]
    chosen = choose_distractors(target, tiny_pool, count=3, tier=1)
    assert chosen == []


def test_selection_is_deterministic() -> None:
    target = _colour("color_red")
    first = [c.code for c in choose_distractors(target, DISTRACTORS, count=3, tier=1)]
    second = [c.code for c in choose_distractors(target, DISTRACTORS, count=3, tier=1)]
    assert first == second


def test_colour_distance_treats_non_colours_as_maximally_distant() -> None:
    """A toothbrush cannot be confused with a colour by hue."""
    assert colour_distance(_colour("color_red"), _as_distractor(BY_CODE["hh_soap"])) == 1.0


def test_visual_distance_is_symmetric_and_bounded() -> None:
    a, b = _colour("color_red"), _colour("color_blue")
    assert visual_distance(a, b) == pytest.approx(visual_distance(b, a))
    assert 0.0 <= visual_distance(a, b) <= 1.0


# --- manifest ---------------------------------------------------------------

NOW = dt.datetime(2026, 8, 29, 12, 0, tzinfo=dt.UTC)
CHILD = ChildSettings(wait_time_ms=8000, max_choices=2, audio_rate_pct=85, calm_mode=False)
LADDER = build_prompt_ladder(gestural_audio="a.opus", partial_audio="b.opus", model_audio="c.opus")


def _activity(**overrides: object) -> ActivityEntry:
    base: dict[str, object] = {
        "id": "act1",
        "kind": "listen_point",
        "skill_id": "color_red",
        "instruction_ar": "وريني الأحمر",
        "instruction_audio": "i.opus",
        "choices": (
            ChoiceEntry("color_red", "red.webp", "مربع أحمر", True),
            ChoiceEntry("body_eye", "eye.webp", "عين", False),
        ),
        "prompt_ladder": LADDER,
        "success_audio": ("bravo.opus",),
        "retry_audio": ("again.opus",),
    }
    base.update(overrides)
    return ActivityEntry(**base)  # type: ignore[arg-type]


def _manifest(*activities: ActivityEntry) -> object:
    return build_manifest(
        session_id="s1",
        child=CHILD,
        activities=activities or (_activity(),),
        closing_audio="bye.opus",
        now=NOW,
    )


def test_a_well_formed_manifest_validates() -> None:
    assert validate(_manifest()) == []  # type: ignore[arg-type]


def test_the_prompt_ladder_always_ends_by_giving_the_answer() -> None:
    """The child never reaches a dead end."""
    assert [rung.level for rung in LADDER] == [
        "gestural",
        "partial_verbal",
        "full_model",
    ]
    assert LADDER[-1].auto_select is True
    assert LADDER[0].highlight == "correct"


def test_a_missing_audio_file_blocks_publication() -> None:
    broken = _manifest(_activity(instruction_audio=""))
    assert "act1:instruction_audio" in missing_media(broken)  # type: ignore[arg-type]
    assert validate(broken)  # type: ignore[arg-type]


def test_a_missing_alt_text_blocks_publication() -> None:
    """Alt text is mandatory: it is the accessibility contract."""
    broken = _manifest(
        _activity(
            choices=(
                ChoiceEntry("color_red", "red.webp", "", True),
                ChoiceEntry("body_eye", "eye.webp", "عين", False),
            )
        )
    )
    assert any("alt_ar" in item for item in missing_media(broken))  # type: ignore[arg-type]


def test_exactly_one_choice_must_be_correct() -> None:
    two_correct = _manifest(
        _activity(
            choices=(
                ChoiceEntry("color_red", "r.webp", "أحمر", True),
                ChoiceEntry("body_eye", "e.webp", "عين", True),
            )
        )
    )
    assert any("correct choices" in p for p in validate(two_correct))  # type: ignore[arg-type]

    none_correct = _manifest(
        _activity(
            choices=(
                ChoiceEntry("color_red", "r.webp", "أحمر", False),
                ChoiceEntry("body_eye", "e.webp", "عين", False),
            )
        )
    )
    assert any("correct choices" in p for p in validate(none_correct))  # type: ignore[arg-type]


def test_an_activity_may_not_exceed_the_childs_max_choices() -> None:
    """The accessibility profile is a hard limit, not a hint."""
    too_many = _manifest(
        _activity(
            choices=(
                ChoiceEntry("color_red", "r.webp", "أحمر", True),
                ChoiceEntry("body_eye", "e.webp", "عين", False),
                ChoiceEntry("hh_soap", "s.webp", "صابونة", False),
            )
        )
    )
    assert any("max_choices" in p for p in validate(too_many))  # type: ignore[arg-type]


def test_the_correct_choice_must_be_the_activitys_own_skill() -> None:
    mismatched = _manifest(_activity(skill_id="color_blue"))
    assert any("own skill" in p for p in validate(mismatched))  # type: ignore[arg-type]


def test_a_duplicated_choice_is_rejected() -> None:
    duplicated = _manifest(
        _activity(
            choices=(
                ChoiceEntry("color_red", "r.webp", "أحمر", True),
                ChoiceEntry("color_red", "r.webp", "أحمر", False),
            )
        )
    )
    assert any("twice" in p for p in validate(duplicated))  # type: ignore[arg-type]


def test_a_single_choice_activity_is_rejected() -> None:
    lone = _manifest(_activity(choices=(ChoiceEntry("color_red", "r.webp", "أحمر", True),)))
    assert any("fewer than 2" in p for p in validate(lone))  # type: ignore[arg-type]


def test_an_overlong_instruction_is_rejected() -> None:
    wordy = _manifest(_activity(instruction_ar="واحد اتنين تلاتة اربعة خمسة ستة"))
    assert any("words" in p for p in validate(wordy))  # type: ignore[arg-type]


def test_a_manifest_without_closing_audio_is_rejected() -> None:
    manifest = build_manifest(
        session_id="s1",
        child=CHILD,
        activities=(_activity(),),
        closing_audio="",
        now=NOW,
    )
    assert "closing_audio" in missing_media(manifest)


def test_a_manifest_expires() -> None:
    """It carries pre-signed URLs, so it must not outlive them."""
    manifest = _manifest()
    assert manifest.expires_at > NOW.isoformat()  # type: ignore[attr-defined]


def test_a_manifest_serialises_to_plain_json_types() -> None:
    import json

    payload = _manifest().to_dict()  # type: ignore[attr-defined]
    assert json.loads(json.dumps(payload))["session_id"] == "s1"


def test_a_missing_ladder_audio_blocks_publication() -> None:
    from app.modules.content.domain.manifest import PromptRung

    broken = _manifest(_activity(prompt_ladder=(PromptRung(level="gestural", audio=""),)))
    assert any("ladder" in item for item in missing_media(broken))  # type: ignore[arg-type]


def test_missing_success_or_retry_audio_blocks_publication() -> None:
    assert any(
        "success_audio" in item
        for item in missing_media(_manifest(_activity(success_audio=())))  # type: ignore[arg-type]
    )
    assert any(
        "retry_audio" in item
        for item in missing_media(_manifest(_activity(retry_audio=())))  # type: ignore[arg-type]
    )


def test_a_missing_choice_image_blocks_publication() -> None:
    broken = _manifest(
        _activity(
            choices=(
                ChoiceEntry("color_red", "", "أحمر", True),
                ChoiceEntry("body_eye", "e.webp", "عين", False),
            )
        )
    )
    assert any("image" in item for item in missing_media(broken))  # type: ignore[arg-type]
