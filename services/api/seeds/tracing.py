"""Reference paths for the tracing activity.

================================================================================
PLACEHOLDER — NOT REVIEWED BY A HANDWRITING SPECIALIST
================================================================================
Every path below is a geometric approximation of a letter shape, authored to
give `tutor/domain/drawing.py` something real to score against. They are not
transcribed from an Arabic handwriting curriculum, the stroke ORDER and stroke
DIRECTION are not necessarily the ones a child should be taught, and the
diacritic dots are deliberately omitted from the traced path (a child traces the
body of ب; the dot is drawn for them).

What that means concretely: a child can pass a tracing activity here by
producing the right SHAPE, and this file makes no claim that the right shape is
the right thing to teach first, or that these are the strokes an Egyptian
first-grade curriculum uses.

A handwriting or occupational-therapy review is required before any of this is
shown to a family. → REVIEW-QUEUE.md #14
================================================================================

Coordinates are in a unit box with (0, 0) at the TOP LEFT and y increasing
downward — the canvas convention, so the client renders the same numbers it
would draw with. A path is a tuple of strokes; a stroke is a tuple of points;
the renderer and the scorer both walk them the same way.

Only skills that appear here can be taught with `trace_letter`. That is checked
rather than assumed: `has_reference()` is what the guardrail asks, and a skill
with no path falls back to selection rather than showing a child a blank guide.
"""

from __future__ import annotations

import math

Point = tuple[float, float]
Stroke = tuple[Point, ...]
Path = tuple[Stroke, ...]

WATERMARK = "PLACEHOLDER — geometric approximation, not a handwriting reference"


def _line(start: Point, end: Point, steps: int = 12) -> Stroke:
    (x1, y1), (x2, y2) = start, end
    return tuple((x1 + (x2 - x1) * i / steps, y1 + (y2 - y1) * i / steps) for i in range(steps + 1))


def _arc(
    centre: Point,
    radius_x: float,
    radius_y: float,
    start_deg: float,
    end_deg: float,
    steps: int = 24,
) -> Stroke:
    """An elliptical arc. Angles in degrees, measured clockwise from east.

    Clockwise because y increases downward here, so the ordinary
    counter-clockwise convention would draw every curve upside down.
    """
    cx, cy = centre
    points: list[Point] = []
    for index in range(steps + 1):
        angle = math.radians(start_deg + (end_deg - start_deg) * index / steps)
        points.append((cx + radius_x * math.cos(angle), cy + radius_y * math.sin(angle)))
    return tuple(points)


def _join(*strokes: Stroke) -> Stroke:
    """Concatenate strokes drawn without lifting the pen."""
    merged: list[Point] = []
    for stroke in strokes:
        merged.extend(stroke if not merged else stroke[1:])
    return tuple(merged)


#: The shallow bowl shared by ب ت ث — one stroke, left to right, dipping in the
#: middle. Arabic is written right to left, and the stroke order here is a
#: PLACEHOLDER decision like everything else in this file.
_BOWL = _join(
    _line((0.20, 0.40), (0.28, 0.52), steps=4),
    _arc((0.50, 0.50), 0.22, 0.16, 145, 35, steps=20),
    _line((0.72, 0.52), (0.80, 0.40), steps=4),
)

#: The deeper bowl of ن — same family, more curve.
_DEEP_BOWL = _join(
    _line((0.22, 0.34), (0.28, 0.52), steps=5),
    _arc((0.50, 0.50), 0.22, 0.24, 145, 35, steps=22),
    _line((0.72, 0.52), (0.78, 0.34), steps=5),
)

#: A closed ring, for ه and ٥.
_RING = _arc((0.50, 0.50), 0.20, 0.24, 0, 360, steps=32)


REFERENCE_PATHS: dict[str, Path] = {
    # --- letters -----------------------------------------------------------
    # A single downstroke. The hamza is drawn for the child, not traced.
    "letter_alef": (_line((0.50, 0.18), (0.50, 0.82), steps=16),),
    "letter_baa": (_BOWL,),
    "letter_taa": (_BOWL,),
    "letter_thaa": (_BOWL,),
    "letter_noon": (_DEEP_BOWL,),
    "letter_haa2": (_RING,),
    # د: a hook opening to the left.
    "letter_dal": (
        _join(
            _line((0.66, 0.30), (0.44, 0.36), steps=6),
            _arc((0.44, 0.52), 0.14, 0.18, 270, 90, steps=16),
            _line((0.44, 0.70), (0.66, 0.70), steps=6),
        ),
    ),
    "letter_thal": (
        _join(
            _line((0.66, 0.30), (0.44, 0.36), steps=6),
            _arc((0.44, 0.52), 0.14, 0.18, 270, 90, steps=16),
            _line((0.44, 0.70), (0.66, 0.70), steps=6),
        ),
    ),
    # ر: a diagonal falling to the left with a tail.
    "letter_raa": (
        _join(
            _line((0.68, 0.30), (0.52, 0.50), steps=8),
            _arc((0.40, 0.52), 0.16, 0.22, 340, 100, steps=16),
        ),
    ),
    "letter_zay": (
        _join(
            _line((0.68, 0.30), (0.52, 0.50), steps=8),
            _arc((0.40, 0.52), 0.16, 0.22, 340, 100, steps=16),
        ),
    ),
    # ل: a downstroke that hooks left at the foot.
    "letter_lam": (
        _join(
            _line((0.64, 0.18), (0.64, 0.58), steps=12),
            _arc((0.46, 0.58), 0.18, 0.22, 0, 110, steps=16),
        ),
    ),
    # م: a small ring with a tail dropping from it.
    "letter_meem": (
        _join(
            _arc((0.52, 0.40), 0.14, 0.14, 0, 360, steps=22),
            _line((0.66, 0.40), (0.66, 0.80), steps=10),
        ),
    ),
    # و: a ring with a tail falling to the left.
    "letter_waw": (
        _join(
            _arc((0.54, 0.36), 0.15, 0.15, 90, 400, steps=24),
            _line((0.54, 0.51), (0.36, 0.80), steps=10),
        ),
    ),
    # --- numerals ----------------------------------------------------------
    # ١ is a plain downstroke; ٥ is a ring; ٧ is a V; ٨ is an inverted V.
    "num_1": (_line((0.50, 0.20), (0.50, 0.80), steps=16),),
    "num_5": (_RING,),
    "num_7": (
        _join(
            _line((0.30, 0.28), (0.50, 0.74), steps=10),
            _line((0.50, 0.74), (0.70, 0.28), steps=10),
        ),
    ),
    "num_8": (
        _join(
            _line((0.30, 0.74), (0.50, 0.28), steps=10),
            _line((0.50, 0.28), (0.70, 0.74), steps=10),
        ),
    ),
    # ٢ — a hook, drawn as the mirror of ٧ with a flat foot.
    "num_2": (
        _join(
            _line((0.32, 0.32), (0.52, 0.32), steps=6),
            _arc((0.52, 0.50), 0.16, 0.18, 270, 90, steps=16),
            _line((0.52, 0.68), (0.32, 0.68), steps=6),
        ),
    ),
}


def has_reference(skill_code: str) -> bool:
    """Whether this skill can be traced at all.

    The guardrail asks this before letting a decision choose `trace_letter`. A
    child shown a tracing activity with no guide has been asked to trace
    nothing, and would fail it.
    """
    return skill_code in REFERENCE_PATHS


def reference_path(skill_code: str) -> Path:
    return REFERENCE_PATHS.get(skill_code, ())


def traceable_skills() -> tuple[str, ...]:
    return tuple(sorted(REFERENCE_PATHS))


__all__ = [
    "REFERENCE_PATHS",
    "WATERMARK",
    "Path",
    "Point",
    "Stroke",
    "has_reference",
    "reference_path",
    "traceable_skills",
]
