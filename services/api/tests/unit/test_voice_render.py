"""T09 — the SSML template, the inventory, the publish gate and the exporter.

After docs/12 §Δ2 there is no runtime TTS, so "the corpus is complete" is not a
performance property any more. It is the difference between a child hearing an
instruction and a child sitting in silence, which is why the publish gate is
tested harder than the renderer.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from seeds.curriculum import (
    ACTIVITY_TEMPLATES,
    RETRY_POOL,
    SUCCESS_POOL,
    build_skills,
)
from tools.asr_finetune.export import (
    MAX_PER_CHILD_PER_SKILL,
    ConsentViolation,
    Triple,
    select,
    to_jsonl,
    write,
)
from tools.voice_render.plan import (
    build_plan,
    loudness_outliers,
    publish_blockers,
)

from app.modules.voice.domain.inventory import (
    RenderedAsset,
    SkillSpec,
    TemplateSpec,
    build_inventory,
    content_hashes,
    missing_assets,
    unvowelised_keys,
)
from app.modules.voice.domain.ssml import (
    LEAD_BREAK_MS,
    TARGET_LUFS,
    TRAIL_BREAK_MS,
    UnvowelisedText,
    Utterance,
    build_ssml,
    cache_key,
    clamp_rate,
    loudness_within_tolerance,
    needs_vowelisation,
    rate_attribute,
)

VOWELISED = Utterance(key="skill:color_red", text_vowelised="الأَحْمَر", emphasis="الأَحْمَر")


# --- SSML ------------------------------------------------------------------


def test_ssml_matches_the_template_in_docs_04d() -> None:
    ssml = build_ssml(VOWELISED)
    assert 'xml:lang="ar-EG"' in ssml
    assert f'<break time="{LEAD_BREAK_MS}ms"/>' in ssml
    assert f'<break time="{TRAIL_BREAK_MS}ms"/>' in ssml
    assert 'rate="-15%"' in ssml
    assert 'pitch="+4%"' in ssml
    assert '<emphasis level="moderate">' in ssml


def test_the_trailing_pause_is_six_hundred_milliseconds() -> None:
    """Not a style choice.

    docs/04d §2: the child needs the utterance to have clearly *ended* before
    the wait timer starts. Shortening this makes the whole prompt ladder fire
    early.
    """
    assert TRAIL_BREAK_MS == 600


def test_rate_is_relative_and_clamped() -> None:
    assert rate_attribute(85) == "-15%"
    assert rate_attribute(100) == "+0%"
    assert rate_attribute(110) == "+10%"
    assert clamp_rate(20) == 60
    assert clamp_rate(500) == 110
    assert rate_attribute(20) == "-40%"


def test_unvowelised_text_is_refused_in_the_request_path() -> None:
    """The single most common Arabic TTS bug, made unrepresentable."""
    bare = Utterance(key="skill:x", text_vowelised="أحمر")
    assert needs_vowelisation("أحمر")
    assert not needs_vowelisation("الأَحْمَر")
    with pytest.raises(UnvowelisedText):
        build_ssml(bare)
    # The renderer may still build it, in order to report every offender at once.
    assert build_ssml(bare, require_vowelised=False)


def test_text_with_no_arabic_letters_is_not_flagged() -> None:
    assert not needs_vowelisation("123")
    assert not needs_vowelisation("")


def test_emphasis_is_only_applied_when_the_target_is_present() -> None:
    absent = Utterance(key="k", text_vowelised="وَرِّيني", emphasis="الأَحْمَر")
    assert "<emphasis" not in build_ssml(absent)


def test_ssml_escapes_markup_in_the_text() -> None:
    hostile = Utterance(key="k", text_vowelised="أَ<script>", emphasis="")
    assert "<script>" not in build_ssml(hostile)


def test_cache_key_changes_with_voice_rate_pitch_and_text() -> None:
    base = cache_key(VOWELISED, build_ssml(VOWELISED))
    assert base == cache_key(VOWELISED, build_ssml(VOWELISED))

    from dataclasses import replace

    for variant in (
        replace(VOWELISED, voice="other"),
        replace(VOWELISED, rate_pct=90),
        replace(VOWELISED, pitch="+0%"),
        replace(VOWELISED, text_vowelised="الأَزْرَق"),
    ):
        assert cache_key(variant, build_ssml(variant)) != base


def test_loudness_tolerance() -> None:
    assert loudness_within_tolerance(TARGET_LUFS)
    assert loudness_within_tolerance(TARGET_LUFS + 1.0)
    assert not loudness_within_tolerance(TARGET_LUFS + 1.1)


# --- the inventory ---------------------------------------------------------


def build_full_inventory() -> list[Utterance]:
    skills = [
        SkillSpec(s.code, s.label_vowelised, s.label_egy, s.difficulty_tier) for s in build_skills()
    ]
    templates = [TemplateSpec(t.code, t.instruction_ar, t.min_tier) for t in ACTIVITY_TEMPLATES]
    return build_inventory(
        skills=skills,
        templates=templates,
        success_lines=SUCCESS_POOL,
        retry_lines=RETRY_POOL,
        item_prompts=[(f"item_{n:03d}", f"سؤال {n}") for n in range(120)],
        ui_lines=[(f"ui_{n:02d}", f"جملة {n}") for n in range(80)],
    )


def test_the_inventory_is_about_eight_hundred_and_fifty_items() -> None:
    """docs/02 §10.4 sizes the corpus at ~850 files."""
    inventory = build_full_inventory()
    assert 600 <= len(inventory) <= 1100, len(inventory)


def test_inventory_keys_are_unique() -> None:
    inventory = build_full_inventory()
    keys = [item.key for item in inventory]
    assert len(keys) == len(set(keys))


def test_identical_instruction_text_is_rendered_once() -> None:
    """Three templates share "وريني {label}"; rendering it three times would
    spend a third of the corpus on identical audio."""
    skills = [SkillSpec("s1", "وَاحِد", "واحد", 4)]
    templates = [
        TemplateSpec("a", "وريني {label}", 1),
        TemplateSpec("b", "وريني {label}", 1),
    ]
    inventory = build_inventory(
        skills=skills,
        templates=templates,
        success_lines=(),
        retry_lines=(),
        item_prompts=[],
        ui_lines=[],
    )
    instructions = [item for item in inventory if item.kind == "instruction"]
    assert len(instructions) == 1


def test_a_template_below_a_skills_tier_is_not_rendered() -> None:
    skills = [SkillSpec("s1", "وَاحِد", "واحد", 1)]
    templates = [TemplateSpec("hard", "وصّل {label}", 3)]
    inventory = build_inventory(
        skills=skills,
        templates=templates,
        success_lines=(),
        retry_lines=(),
        item_prompts=[],
        ui_lines=[],
    )
    assert [item for item in inventory if item.kind == "instruction"] == []


def test_a_colloquial_form_gets_its_own_clip() -> None:
    skills = [SkillSpec("num_2", "٢", "اتنين", 2)]
    inventory = build_inventory(
        skills=skills,
        templates=[],
        success_lines=(),
        retry_lines=(),
        item_prompts=[],
        ui_lines=[],
    )
    assert {item.key for item in inventory} == {"skill:num_2", "skill_egy:num_2"}


def test_the_whole_curriculum_is_currently_unvowelised() -> None:
    """A finding, asserted so it cannot be forgotten.

    `seeds/curriculum.py` ships `label_vowelised` as an explicit placeholder, so
    every skill clip would be mispronounced. This test documents the size of the
    gap; it will invert when a native speaker supplies real tashkeel, and the
    publish gate below is what stops the corpus shipping before then.
    → REVIEW-QUEUE.md
    """
    inventory = build_full_inventory()
    offenders = unvowelised_keys(inventory)
    assert len(offenders) > 80


# --- the publish gate ------------------------------------------------------


def asset(key: str, digest: str, *, lufs: float = TARGET_LUFS) -> RenderedAsset:
    return RenderedAsset(
        key=key, content_hash=digest, url=f"https://r2/{key}.opus", lufs=lufs, duration_ms=900
    )


def small_inventory() -> list[Utterance]:
    return [
        Utterance(key="a", text_vowelised="وَاحِد"),
        Utterance(key="b", text_vowelised="اتْنين"),
    ]


def test_a_complete_render_has_no_missing_assets() -> None:
    inventory = small_inventory()
    hashes = content_hashes(inventory)
    rendered = {key: asset(key, digest) for key, digest in hashes.items()}
    assert missing_assets(inventory, rendered) == []
    assert publish_blockers(inventory, rendered) == []


def test_a_missing_asset_blocks_publish() -> None:
    inventory = small_inventory()
    hashes = content_hashes(inventory)
    rendered = {"a": asset("a", hashes["a"])}
    assert missing_assets(inventory, rendered) == ["b:absent"]
    assert any(
        blocker.startswith("unrendered:b") for blocker in publish_blockers(inventory, rendered)
    )


def test_a_stale_asset_blocks_publish() -> None:
    inventory = small_inventory()
    hashes = content_hashes(inventory)
    rendered = {"a": asset("a", hashes["a"]), "b": asset("b", "stale-hash")}
    assert missing_assets(inventory, rendered) == ["b:stale"]


def test_an_asset_with_no_url_blocks_publish() -> None:
    inventory = small_inventory()
    hashes = content_hashes(inventory)
    rendered = {
        "a": asset("a", hashes["a"]),
        "b": RenderedAsset("b", hashes["b"], "", TARGET_LUFS, 900),
    }
    assert missing_assets(inventory, rendered) == ["b:no_url"]


def test_loudness_outside_one_lufs_blocks_publish() -> None:
    """docs/04d §2 — a clip louder than its neighbours startles a child."""
    inventory = small_inventory()
    hashes = content_hashes(inventory)
    rendered = {
        "a": asset("a", hashes["a"]),
        "b": asset("b", hashes["b"], lufs=TARGET_LUFS + 2.5),
    }
    assert loudness_outliers(rendered) == [("b", TARGET_LUFS + 2.5)]
    assert any(
        blocker.startswith("loudness:b") for blocker in publish_blockers(inventory, rendered)
    )


def test_unvowelised_text_blocks_publish_before_anything_else() -> None:
    inventory = [Utterance(key="a", text_vowelised="أحمر")]
    blockers = publish_blockers(inventory, {})
    assert blockers[0] == "unvowelised:a"


# --- the render plan is idempotent ----------------------------------------


def test_re_running_a_complete_render_renders_nothing() -> None:
    """docs/12 §3.1: a re-render costs only what changed. That is what makes
    the $0.70 figure true a second time."""
    inventory = small_inventory()
    hashes = content_hashes(inventory)
    rendered = {key: asset(key, digest) for key, digest in hashes.items()}
    plan = build_plan(inventory, rendered)
    assert plan.to_render == ()
    assert set(plan.unchanged) == {"a", "b"}
    assert plan.estimated_usd() == 0.0


def test_changing_one_clip_re_renders_only_that_clip() -> None:
    inventory = small_inventory()
    hashes = content_hashes(inventory)
    rendered = {key: asset(key, digest) for key, digest in hashes.items()}
    rendered["b"] = asset("b", "different")
    plan = build_plan(inventory, rendered)
    assert [item.key for item in plan.to_render] == ["b"]


def test_orphans_are_reported_and_never_deleted() -> None:
    inventory = small_inventory()
    hashes = content_hashes(inventory)
    rendered = {key: asset(key, digest) for key, digest in hashes.items()}
    rendered["gone"] = asset("gone", "x")
    plan = build_plan(inventory, rendered)
    assert plan.orphans == ("gone",)


def test_a_full_corpus_render_fits_the_gpu_budget() -> None:
    """docs/12 §Δ2: under 3 GPU-hours and under $2."""
    inventory = build_full_inventory()
    plan = build_plan(inventory, {})
    assert plan.estimated_gpu_hours() < 3.0
    assert plan.estimated_usd() < 2.0
    assert not plan.is_clean  # the curriculum is still unvowelised


# --- the fine-tune exporter ------------------------------------------------

NOW = dt.datetime(2026, 8, 29, 12, 0, tzinfo=dt.UTC)


def triple(**overrides: object) -> Triple:
    base: dict[str, object] = {
        "child_id": "c1",
        "skill_code": "color_red",
        "expected_word": "أحمر",
        "audio_key": "audio/c1/color_red/a.opus",
        "confirmed": True,
        "recorded_at": NOW - dt.timedelta(days=1),
        "voice_retention_granted": True,
    }
    base.update(overrides)
    return Triple(**base)  # type: ignore[arg-type]


def test_the_exporter_refuses_a_row_without_retention_consent() -> None:
    """docs/12 §3.2 — the flywheel runs on consented audio or it does not run."""
    with pytest.raises(ConsentViolation):
        select([triple(voice_retention_granted=False)], now=NOW)


def test_one_unconsented_row_stops_the_whole_export() -> None:
    """Per row, not per batch: a consented child must not carry the others through."""
    rows = [triple(), triple(audio_key="b.opus", voice_retention_granted=False)]
    with pytest.raises(ConsentViolation):
        select(rows, now=NOW)


def test_unconfirmed_and_expired_rows_are_filtered_not_fatal() -> None:
    rows = [
        triple(),
        triple(audio_key="b.opus", confirmed=False),
        triple(audio_key="c.opus", recorded_at=NOW - dt.timedelta(days=40)),
    ]
    selected, stats = select(rows, now=NOW)
    assert [row.audio_key for row in selected] == ["audio/c1/color_red/a.opus"]
    assert stats.skipped_unconfirmed == 1
    assert stats.skipped_expired == 1


def test_the_per_child_per_skill_cap_is_applied() -> None:
    rows = [
        triple(audio_key=f"{n}.opus", recorded_at=NOW - dt.timedelta(hours=n))
        for n in range(MAX_PER_CHILD_PER_SKILL + 5)
    ]
    selected, stats = select(rows, now=NOW)
    assert len(selected) == MAX_PER_CHILD_PER_SKILL
    assert stats.skipped_over_cap == 5


def test_the_training_set_does_not_identify_the_children_in_it() -> None:
    selected, _ = select([triple()], now=NOW)
    line = to_jsonl(selected)
    assert "c1" not in line.replace("audio/c1/", "")
    assert '"text": "أحمر"' in line
    assert '"language": "ar-EG"' in line


def test_write_produces_a_file(tmp_path: Path) -> None:
    selected, _ = select([triple()], now=NOW)
    destination = tmp_path / "nested" / "train.jsonl"
    assert write(selected, destination) == 1
    assert destination.read_text(encoding="utf-8").endswith("\n")
    assert write([], tmp_path / "empty.jsonl") == 0
