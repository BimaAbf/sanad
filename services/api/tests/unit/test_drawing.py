"""The tracing scorer, and the table the specification requires it to satisfy.

Every negative case and every positive case is run against EVERY reference glyph
in `seeds/tracing.py`, not against one convenient letter. A scorer tuned to ب
that passes a half-drawn م is not a scorer, and the first version of this did
exactly that — م is a ring 0.14 across with a short tail, so most of its
reference sits inside the 0.10 tolerance of its own first half, and a linear
length penalty passed a half-drawn one at 0.68. The squared penalty in
`_length_penalty` is what that measurement bought.

The two numbers the whole file exists to hold apart:

    highest-scoring negative   0.590
    lowest-scoring positive    0.906

with the threshold at 0.62. If a change closes that gap,
`test_the_threshold_separates_every_case` fails and names the case that moved.
"""

from __future__ import annotations

import random

import pytest
from seeds.tracing import reference_path, traceable_skills

from app.modules.tutor.domain.drawing import (
    MIN_DRAWN_LENGTH,
    PASS_THRESHOLD,
    evaluate_drawing,
    path_length,
    resample,
    smooth,
)

CANVAS = 400.0


def _pixels(strokes: list[list[tuple[float, float]]]) -> list[list[tuple[float, float]]]:
    return [[(x * CANVAS, y * CANVAS) for x, y in stroke] for stroke in strokes]


def _trace(
    glyph: str,
    *,
    jitter: float = 0.0,
    fraction: float = 1.0,
    offset_y: float = 0.0,
    seed: int = 1,
) -> list[list[tuple[float, float]]]:
    """A synthetic hand tracing the reference, with the flaws named as arguments."""
    rng = random.Random(seed)
    points = resample([[(x, y) for x, y in stroke] for stroke in reference_path(glyph)])
    kept = points[: max(1, int(len(points) * fraction))]
    return _pixels(
        [
            [
                (
                    x + rng.uniform(-jitter, jitter),
                    y + offset_y + rng.uniform(-jitter, jitter),
                )
                for x, y in kept
            ]
        ]
    )


def _scribble(seed: int = 5) -> list[list[tuple[float, float]]]:
    rng = random.Random(seed)
    return [[(rng.uniform(40, 360), rng.uniform(40, 360)) for _ in range(120)]]


def _negatives(glyph: str) -> dict[str, list[list[tuple[float, float]]]]:
    """Every case the specification's table says must FAIL."""
    return {
        "blank canvas": [],
        "one dot": [[(200.0, 200.0)]],
        "a two-pixel flick": [[(200.0, 200.0), (203.0, 202.0)]],
        "random scribble": _scribble(),
        "the wrong shape entirely": _pixels([[(0.15 + 0.7 * i / 30, 0.85) for i in range(31)]]),
        "half the letter": _trace(glyph, fraction=0.5),
        "a quarter of the letter": _trace(glyph, fraction=0.25),
        "mostly outside the guide": _trace(glyph, offset_y=-0.30),
    }


def _positives(glyph: str) -> dict[str, list[list[tuple[float, float]]]]:
    """Every case that must PASS."""
    return {
        "an accurate trace": _trace(glyph),
        "a slightly shaky trace": _trace(glyph, jitter=0.02, seed=3),
        "a very shaky trace": _trace(glyph, jitter=0.04, seed=4),
        "80% of the letter": _trace(glyph, fraction=0.8, jitter=0.015),
        "a trace offset by 5% of the canvas": _trace(glyph, offset_y=0.05),
        "the letter traced twice over": _trace(glyph) * 2,
    }


# ===========================================================================
# The required table
# ===========================================================================


@pytest.mark.parametrize("glyph", traceable_skills())
def test_every_negative_case_fails_for_every_glyph(glyph: str) -> None:
    reference = reference_path(glyph)
    for name, strokes in _negatives(glyph).items():
        result = evaluate_drawing(strokes, reference, width=CANVAS, height=CANVAS)
        assert not result.passed, f"{glyph}: {name} scored {result.score:.3f} and PASSED"


@pytest.mark.parametrize("glyph", traceable_skills())
def test_every_positive_case_passes_for_every_glyph(glyph: str) -> None:
    reference = reference_path(glyph)
    for name, strokes in _positives(glyph).items():
        result = evaluate_drawing(strokes, reference, width=CANVAS, height=CANVAS)
        assert result.passed, f"{glyph}: {name} scored {result.score:.3f} and FAILED"


def test_the_threshold_separates_every_case_with_room_to_spare() -> None:
    """The gap the threshold sits in, measured across the whole corpus.

    Stated as numbers rather than as "negatives fail": a change that leaves
    every case on the right side of the line but closes the gap to nothing has
    made the scorer fragile, and this is where that shows up.
    """
    worst_positive = 1.0
    best_negative = 0.0
    for glyph in traceable_skills():
        reference = reference_path(glyph)
        for strokes in _negatives(glyph).values():
            best_negative = max(
                best_negative,
                evaluate_drawing(strokes, reference, width=CANVAS, height=CANVAS).score,
            )
        for strokes in _positives(glyph).values():
            worst_positive = min(
                worst_positive,
                evaluate_drawing(strokes, reference, width=CANVAS, height=CANVAS).score,
            )

    assert best_negative < PASS_THRESHOLD < worst_positive
    assert worst_positive - best_negative > 0.25, (
        f"the gap has closed to {worst_positive - best_negative:.3f} "
        f"(negatives up to {best_negative:.3f}, positives from {worst_positive:.3f})"
    )


def test_a_score_exactly_on_the_threshold_passes() -> None:
    """The documented boundary. `>=`, not `>`.

    Constructed rather than searched for: `evaluate_drawing` takes the threshold
    as an argument, so a threshold equal to a known score is a score exactly on
    its own line.
    """
    reference = reference_path("letter_baa")
    strokes = _trace("letter_baa", jitter=0.02, seed=3)
    measured = evaluate_drawing(strokes, reference, width=CANVAS, height=CANVAS)
    on_the_line = evaluate_drawing(
        strokes, reference, width=CANVAS, height=CANVAS, threshold=measured.score
    )
    assert on_the_line.passed
    just_above = evaluate_drawing(
        strokes,
        reference,
        width=CANVAS,
        height=CANVAS,
        threshold=measured.score + 1e-9,
    )
    assert not just_above.passed


# ===========================================================================
# Why each rejection happens, named
# ===========================================================================


def test_an_empty_canvas_is_rejected_before_it_is_scored() -> None:
    result = evaluate_drawing([], reference_path("letter_baa"), width=CANVAS, height=CANVAS)
    assert result.score == 0.0
    assert result.metrics.rejected == "empty"


def test_a_dot_is_rejected_as_too_short_not_as_empty() -> None:
    """The two are different, and the caregiver-facing prompt differs.

    A child who never touched the screen needs the instruction again; a child
    who touched it and lifted needs a demonstration.
    """
    result = evaluate_drawing(
        [[(200.0, 200.0)]], reference_path("letter_baa"), width=CANVAS, height=CANVAS
    )
    assert result.metrics.rejected == "too_short"


def test_a_missing_reference_fails_closed() -> None:
    """No guide means nothing to trace. Passing would pass every child."""
    result = evaluate_drawing(_trace("letter_baa"), [], width=CANVAS, height=CANVAS)
    assert not result.passed
    assert result.metrics.rejected == "no_reference"


def test_a_zero_sized_canvas_is_not_a_crash() -> None:
    result = evaluate_drawing(
        [[(1.0, 1.0), (2.0, 2.0)]], reference_path("letter_baa"), width=0, height=0
    )
    assert not result.passed


def test_a_scribble_is_defeated_by_its_length_and_not_by_its_coverage() -> None:
    """The reason the score is a product rather than a sum, as a measurement.

    A scribble covers the whole letter — it covers the whole canvas — so
    coverage alone would pass it. What fails it is drawing ten times the
    required length.
    """
    result = evaluate_drawing(
        _scribble(), reference_path("letter_baa"), width=CANVAS, height=CANVAS
    )
    assert result.metrics.coverage > 0.8
    assert result.metrics.length_ratio > 5.0
    assert result.score < 0.1


# ===========================================================================
# Device independence
# ===========================================================================


@pytest.mark.parametrize("size", [320.0, 400.0, 768.0, 1024.0])
def test_the_same_drawing_scores_the_same_on_every_canvas_size(size: float) -> None:
    """A 320px phone and a 1024px tablet must agree, or the threshold is a lie."""
    reference = reference_path("letter_noon")
    unit = _trace("letter_noon", jitter=0.02, seed=7)
    scaled = [[(x / CANVAS * size, y / CANVAS * size) for x, y in s] for s in unit]

    baseline = evaluate_drawing(unit, reference, width=CANVAS, height=CANVAS)
    scaled_result = evaluate_drawing(scaled, reference, width=size, height=size)
    assert scaled_result.score == pytest.approx(baseline.score, abs=0.02)


def test_scale_is_not_fitted_so_a_tiny_mark_cannot_become_a_letter() -> None:
    """The failure mode that makes most tracing scorers worthless.

    A perfect ب drawn at a tenth of the size, in the corner. Normalising scale
    would make it a perfect trace; not normalising it makes it what it is.
    """
    reference = reference_path("letter_baa")
    tiny = [
        [(x * 0.1 + 20.0, y * 0.1 + 20.0) for x, y in stroke] for stroke in _trace("letter_baa")
    ]
    result = evaluate_drawing(tiny, reference, width=CANVAS, height=CANVAS)
    assert not result.passed


def test_a_drawing_is_forgiven_a_small_offset_and_not_a_large_one() -> None:
    reference = reference_path("letter_baa")
    small = evaluate_drawing(
        _trace("letter_baa", offset_y=0.04), reference, width=CANVAS, height=CANVAS
    )
    large = evaluate_drawing(
        _trace("letter_baa", offset_y=0.25), reference, width=CANVAS, height=CANVAS
    )
    assert small.passed
    assert not large.passed


# ===========================================================================
# The pure helpers
# ===========================================================================


def test_resampling_makes_the_sample_rate_irrelevant() -> None:
    """A device reporting four times as many points must not score differently."""
    dense = _trace("letter_alef")
    sparse = [stroke[::4] for stroke in dense]
    reference = reference_path("letter_alef")
    assert evaluate_drawing(dense, reference, width=CANVAS, height=CANVAS).score == pytest.approx(
        evaluate_drawing(sparse, reference, width=CANVAS, height=CANVAS).score, abs=0.05
    )


def test_smoothing_keeps_the_endpoints_where_the_child_put_them() -> None:
    """Trimming the ends would cost coverage exactly where a letter is legible."""
    stroke = [(float(i), float(i % 3)) for i in range(40)]
    smoothed = smooth(stroke)
    assert len(smoothed) == len(stroke)
    assert smoothed[0] == pytest.approx(
        (
            sum(x for x, _ in stroke[:3]) / 3,
            sum(y for _, y in stroke[:3]) / 3,
        )
    )


def test_smoothing_removes_the_length_a_tremor_adds() -> None:
    """The reason `length_ratio` is measured after smoothing.

    Uniform noise on every sample of a 200-point stroke multiplies its polyline
    length several times over. A child with a tremor has not drawn four letters.
    """
    straight = [[(x / 100.0, 0.5) for x in range(100)]]
    rng = random.Random(2)
    shaky = [[(x, y + rng.uniform(-0.03, 0.03)) for x, y in straight[0]]]
    assert path_length(shaky) > 2 * path_length(straight)
    assert path_length([smooth(shaky[0])]) < 1.6 * path_length(straight)


def test_pen_up_moves_between_strokes_do_not_count_as_drawn_length() -> None:
    one = [[(0.0, 0.0), (1.0, 0.0)]]
    two = [[(0.0, 0.0), (0.5, 0.0)], [(10.0, 10.0), (10.5, 10.0)]]
    assert path_length(one) == pytest.approx(1.0)
    assert path_length(two) == pytest.approx(1.0)


def test_the_minimum_drawn_length_is_a_fraction_of_the_canvas() -> None:
    """Stated so a change to it is a decision rather than a nudge."""
    assert 0.0 < MIN_DRAWN_LENGTH < 0.5
