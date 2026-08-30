"""The Nour recording script: coverage, duration, and the two banners.

Three properties are worth holding, and all three are about not lying to the
person who books a studio:

  1. **The phonetic-coverage check has to be able to fail.** A checker that
     always says "complete" is worse than none, because it retires a real risk
     on no evidence.
  2. **The duration has to count takes, not lines.** 108 lines at three takes
     each is not a seven-minute session, and someone books a room on this number.
  3. **The DO-NOT-RECORD banner has to appear while the Arabic is unreviewed**,
     and has to disappear when it is not.

Run with the rest of the suite: `just test`, or directly

    uv --directory services/api run pytest ../../tools/voice_render/test_recording_script.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from voice_render.recording_script import (
    TARGET_MINUTES_MIN,
    Block,
    build_blocks,
    estimated_minutes,
    phoneme_coverage,
    recorded_utterances,
    render_markdown,
    shortfall_minutes,
)

LABELS = ("أحمر", "شباك", "جزمة", "صابونة", "عين")
INSTRUCTIONS = ("وريني الكورة", "قول ورايا الكورة")
SUCCESS = ("برافو!",)
RETRY = ("يلا نجرب تاني",)


def _blocks() -> tuple[Block, ...]:
    return build_blocks(
        labels=LABELS,
        instructions=INSTRUCTIONS,
        success_lines=SUCCESS,
        retry_lines=RETRY,
    )


# --- coverage --------------------------------------------------------------


def test_coverage_reports_a_gap_when_one_exists() -> None:
    """The check must be able to fail, or it is decoration.

    Two words cannot exercise 26 phonemes, and the report has to say so.
    """
    coverage = phoneme_coverage(["باب", "ماما"])
    assert not coverage.complete
    assert "$" in coverage.missing  # ش occurs in neither word


def test_coverage_is_complete_for_the_real_curriculum_sized_script() -> None:
    """Not a tautology — it is the finding that the 88 labels are enough.

    If a future curriculum edit drops the only word containing a phoneme, this
    fails and the script gains a section rather than the clone gaining a hole.
    """
    from seeds.curriculum import build_skills

    labels = [skill.label_egy or skill.label_ar for skill in build_skills()]
    coverage = phoneme_coverage(labels)
    assert coverage.complete, f"no curriculum label contains: {sorted(coverage.missing)}"


def test_a_phoneme_no_arabic_grapheme_maps_to_is_not_reported_as_missing() -> None:
    """/v/, /p/ and the rest exist for loanwords. Demanding them would be noise."""
    coverage = phoneme_coverage(["أحمر"])
    assert "v" not in coverage.missing
    assert "p" not in coverage.missing


# --- duration --------------------------------------------------------------


def test_duration_counts_takes_not_lines() -> None:
    blocks = _blocks()
    lines = sum(len(block.lines) for block in blocks)
    assert recorded_utterances(blocks) > lines


def test_the_discarded_warm_up_does_not_count_toward_the_corpus() -> None:
    blocks = _blocks()
    warm_up = blocks[0]
    assert not warm_up.counts_toward_corpus
    without_warm_up = recorded_utterances(blocks)
    counted = recorded_utterances(
        tuple(Block(b.title, b.purpose, b.lines, b.direction, b.takes, True) for b in blocks)
    )
    assert counted > without_warm_up


def test_a_short_script_reports_its_shortfall() -> None:
    blocks = _blocks()
    assert estimated_minutes(blocks) < TARGET_MINUTES_MIN
    assert shortfall_minutes(blocks) > 0


def test_a_long_enough_script_reports_no_shortfall() -> None:
    blocks = (Block("bulk", "x", tuple(f"كلمة {n}" for n in range(400)), takes=1),)
    assert shortfall_minutes(blocks) == 0.0


# --- the document ----------------------------------------------------------


def test_unreviewed_arabic_carries_a_do_not_record_banner() -> None:
    """The most expensive mistake available here is recording wrong Arabic."""
    document = render_markdown(_blocks(), reviewed_by="")
    assert "DO NOT RECORD" in document
    assert "REVIEW-QUEUE #1 and #6" in document


def test_a_reviewed_script_names_its_reviewer_and_drops_the_banner() -> None:
    document = render_markdown(_blocks(), reviewed_by="Dr Somebody")
    assert "DO NOT RECORD" not in document
    assert "Dr Somebody" in document


def test_the_document_states_the_shortfall_and_what_fills_it() -> None:
    document = render_markdown(_blocks())
    assert "short of the" in document
    assert "connected Egyptian speech" in document


def test_the_release_is_named_before_the_recording_directions() -> None:
    """Order on the page is the order of operations: contract, then microphone."""
    document = render_markdown(_blocks())
    assert document.index("release comes first") < document.index("## 1.")


def test_every_line_reaches_the_document() -> None:
    document = render_markdown(_blocks())
    for label in LABELS:
        assert label in document
    for line in (*INSTRUCTIONS, *SUCCESS, *RETRY):
        assert line in document
