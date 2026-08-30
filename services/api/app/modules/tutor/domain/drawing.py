"""Tracing evaluation. Pure, deterministic, no model anywhere near it.

A child traces ب on a canvas. This module decides whether they traced it. The
whole point is that the decision is arithmetic over the strokes the child
actually made, reproducible from the stored numbers, and identical on every
device — so "the drawing passed" is a fact rather than an opinion, and a
caregiver asking why can be shown the four numbers that produced it.

--------------------------------------------------------------------------------
THE PIPELINE
--------------------------------------------------------------------------------
    raw strokes in device pixels
      -> normalise by the canvas the child actually drew on   (unit box)
      -> resample both paths to a fixed spacing               (device-independent)
      -> bounded translation search                           (forgive a small offset)
      -> four metrics                                         (coverage, mean distance,
                                                               outside ratio, length ratio)
      -> one score                                            (a product, so any one
                                                               failure is fatal)
      -> threshold                                            (PASS / RETRY)

--------------------------------------------------------------------------------
WHY THE NORMALISATION IS BOUNDED
--------------------------------------------------------------------------------
"Normalise position and scale" is the obvious instruction and, taken literally,
it is what makes a tracing scorer worthless: fit any mark to the reference's
bounding box and a 4 mm dot becomes a perfect ب. So:

  * dividing by the canvas size is unconditional — it is what makes a 320 px
    phone and a 1024 px tablet produce the same score, and it cannot be gamed;
  * translation is searched over a small grid, ±6% of the box, because a child
    whose hand starts slightly left of the guide has traced the letter;
  * **scale is not fitted at all.** The guide is drawn at a known place and a
    known size and the child is asked to go over it. A mark of the wrong size
    is a mark of the wrong size, and `length_ratio` prices it.

--------------------------------------------------------------------------------
WHY THE SCORE IS A PRODUCT
--------------------------------------------------------------------------------
    score = coverage x (1 - outside_ratio) x length_penalty

A weighted sum lets a scribble buy back its coverage: cover every part of the
letter by covering the whole canvas, and a sum still gives you two thirds of the
marks. A product does not — anything close to zero on any factor is close to
zero overall, which is the behaviour the test table demands (blank, dot,
scribble, wrong shape, partial, mostly-outside all FAIL).

None of these constants is clinically validated. An occupational therapist has
not seen them. → REVIEW-QUEUE.md
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

Point = tuple[float, float]
Path = Sequence[Sequence[Point]]

#: The pass mark, measured rather than picked. Swept over all eighteen
#: reference glyphs x seven negative cases (blank, dot, scribble, wrong shape,
#: half, quarter, offset by 0.30) and six positive ones (accurate, two
#: tremor levels, 80% traced, offset by 0.05, traced twice):
#:
#:     highest-scoring negative  0.590   (a half-traced م)
#:     lowest-scoring positive   0.906   (a doubled trace of ب)
#:
#: 0.62 sits in that gap, nearer the negatives, because the cost of failing a
#: child who traced it is one more go and the cost of passing a child who did
#: not is a wrong entry in their record. `tests/unit/test_drawing.py` re-runs
#: the whole sweep, so a change that closes the gap fails there.
PASS_THRESHOLD = 0.62

#: How far from the reference a drawn point may be and still count as "on it",
#: as a fraction of the unit box. 0.10 is roughly a fingertip on a phone: at a
#: 320 px canvas it is 32 px, and the median adult fingertip contact patch is
#: about 8 mm.
TOLERANCE = 0.10

#: Both paths are resampled to this spacing before anything is measured, so
#: neither a device that reports 240 points per second nor one that reports 60
#: changes the answer.
SAMPLE_SPACING = 0.01

#: Below this total drawn length there is nothing to score. A single dot has a
#: length of zero; a two-pixel flick is not an attempt at a letter.
MIN_DRAWN_LENGTH = 0.15

#: Translation search: offsets from -LIMIT to +LIMIT in STEP increments, on both
#: axes — 7 x 7 = 49 candidates.
#:
#: The step is 0.02 and not 0.01 because the second decimal place is not a
#: meaningful distinction: 0.02 of the unit box is 8px on a 400px canvas, well
#: inside the 0.10 tolerance, and halving it quadrupled the work for a score
#: that moved in the third decimal. A tracing is scored while a child waits.
TRANSLATION_LIMIT = 0.06
TRANSLATION_STEP = 0.02

#: The band of drawn-to-reference length ratio that costs nothing. Below it the
#: child stopped early; above it they went round more than once, or scribbled.
LENGTH_RATIO_MIN = 0.60
LENGTH_RATIO_MAX = 1.80

#: How fast the length penalty falls away outside that band. At `2 x` over the
#: ceiling the penalty is zero, which is where an ordinary scribble lands.
LENGTH_PENALTY_SLOPE = 1.0

#: Distances are reported capped at this value. The metrics answer "how far off
#: the guide was this", and everything past a sixth of the canvas is equally far
#: off — while an uncapped nearest-neighbour search has to look at every
#: reference point rather than at the handful nearby. See `_Nearest`.
MAX_REPORTED_DISTANCE = 0.25

#: Moving-average window applied to each drawn stroke before anything is
#: measured. Touch hardware reports 60-240 samples a second and a child with a
#: tremor produces a stroke whose polyline is several times longer than the line
#: it visibly traces — so an unsmoothed `length_ratio` would fail a child for
#: their hands, which is the one thing `bkt.P_SLIP = 0.25` exists to avoid.
#: Five samples is short enough to leave a real letter's corners intact; the
#: reference path is NOT smoothed, because it has no noise to remove.
SMOOTHING_WINDOW = 5


@dataclass(frozen=True, slots=True)
class DrawingMetrics:
    """Everything the score was computed from. Persisted with the attempt.

    Stored rather than derived later because the reference path can change with
    a curriculum edit, and a stored score whose inputs are gone is a number
    nobody can check.
    """

    coverage: float
    mean_distance: float
    outside_ratio: float
    length_ratio: float
    sampled_points: int
    #: Set when the submission was rejected before scoring — "empty",
    #: "too_short", or "" when it was scored normally.
    rejected: str = ""

    def as_json(self) -> dict[str, float | int | str]:
        return {
            "coverage": round(self.coverage, 4),
            "mean_distance": round(self.mean_distance, 4),
            "outside_ratio": round(self.outside_ratio, 4),
            "length_ratio": round(self.length_ratio, 4),
            "sampled_points": self.sampled_points,
            "rejected": self.rejected,
        }


@dataclass(frozen=True, slots=True)
class DrawingResult:
    score: float
    threshold: float
    passed: bool
    metrics: DrawingMetrics


def _to_unit_box(strokes: Path, *, width: float, height: float) -> list[list[Point]]:
    """Device pixels to a unit box, using the canvas the child drew on.

    Both axes are divided by the same number — the longer side — so a wide
    canvas does not stretch a circle into an ellipse. A drawing made on a
    1024 px tablet and the same drawing made on a 320 px phone normalise to the
    same points, which is the only reason a single threshold can exist.
    """
    longest = max(width, height)
    if longest <= 0:
        return []
    return [
        [(float(x) / longest, float(y) / longest) for x, y in stroke]
        for stroke in strokes
        if len(stroke) >= 1
    ]


def smooth(stroke: Sequence[Point], window: int = SMOOTHING_WINDOW) -> list[Point]:
    """A centred moving average, with the ends held rather than shortened.

    Holding the ends matters: a child's stroke starts and finishes where they
    put their finger down and lifted it, and trimming those would move both
    endpoints inward and cost coverage at exactly the two places a letter is
    most identifiable.
    """
    points = [(float(x), float(y)) for x, y in stroke]
    if window <= 1 or len(points) <= window:
        return points
    half = window // 2
    out: list[Point] = []
    for index in range(len(points)):
        low = max(0, index - half)
        high = min(len(points), index + half + 1)
        chunk = points[low:high]
        out.append(
            (
                sum(px for px, _ in chunk) / len(chunk),
                sum(py for _, py in chunk) / len(chunk),
            )
        )
    return out


def path_length(strokes: Sequence[Sequence[Point]]) -> float:
    """Total pen-down distance. Pen-up moves between strokes do not count."""
    total = 0.0
    for stroke in strokes:
        for (x1, y1), (x2, y2) in pairwise(stroke):
            total += math.hypot(x2 - x1, y2 - y1)
    return total


def resample(strokes: Sequence[Sequence[Point]], spacing: float = SAMPLE_SPACING) -> list[Point]:
    """Every stroke walked at a fixed spacing, flattened to one point list.

    A device that samples fast would otherwise put hundreds of points in the
    place where the child paused, and every metric here is a mean over points.
    """
    points: list[Point] = []
    for stroke in strokes:
        if not stroke:
            continue
        points.append((float(stroke[0][0]), float(stroke[0][1])))
        carried = 0.0
        for (x1, y1), (x2, y2) in pairwise(stroke):
            segment = math.hypot(x2 - x1, y2 - y1)
            if segment <= 0:
                continue
            travelled = spacing - carried
            while travelled <= segment:
                ratio = travelled / segment
                points.append((x1 + (x2 - x1) * ratio, y1 + (y2 - y1) * ratio))
                travelled += spacing
            carried = (carried + segment) % spacing
    return points


class _Nearest:
    """Nearest-point lookup over a fixed cloud, bucketed into a uniform grid.

    The naive version was O(points x cloud) and this is called once per drawn
    point per candidate offset — 169 offsets x ~250 points x ~250 reference
    points is 10 million distance computations for ONE tracing, which took
    seconds in Python and would have been seconds a child spent waiting.

    Bucketing into cells of `MAX_REPORTED_DISTANCE` and searching the 3x3
    neighbourhood makes it O(points), because a point further away than one cell
    ring cannot be nearer than the cap — and the cap is all the caller needs,
    since every distance past it is equally "off the guide".
    """

    __slots__ = ("_cells", "_size")

    def __init__(self, cloud: Sequence[Point]) -> None:
        # Cell size is the TOLERANCE, not the reporting cap. A 3x3 ring of
        # tolerance-sized cells is guaranteed to contain anything within the
        # tolerance, and sizing the cells at the cap instead put the whole
        # letter into four cells — which is a grid that scans everything and
        # saves nothing.
        self._size = TOLERANCE
        self._cells: dict[tuple[int, int], list[Point]] = {}
        for point in cloud:
            self._cells.setdefault(self._cell(point), []).append(point)

    def _cell(self, point: Point) -> tuple[int, int]:
        return (int(point[0] // self._size), int(point[1] // self._size))

    def distance(self, point: Point) -> float:
        """Distance to the nearest point of the cloud, capped.

        A query with nothing in its 3x3 ring is further than one cell away, so
        the answer is "past the tolerance" — and the cap is what is reported,
        because every distance past it is equally off the guide.
        """
        px, py = point
        cx, cy = self._cell(point)
        best = MAX_REPORTED_DISTANCE
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for qx, qy in self._cells.get((cx + dx, cy + dy), ()):
                    distance = math.hypot(px - qx, py - qy)
                    if distance < best:
                        best = distance
        return best


def _nearest_distance(point: Point, cloud: Sequence[Point]) -> float:
    """The single-shot form. Only used on the rejection paths, where there is
    one point to place and building an index would cost more than it saves."""
    return _Nearest(cloud).distance(point)


def _measure(
    drawn: Sequence[Point],
    reference: Sequence[Point],
    *,
    drawn_index: _Nearest,
    reference_index: _Nearest,
    offset: Point,
) -> tuple[float, float, float]:
    """(coverage, mean_distance, outside_ratio) for one candidate offset.

    BOTH indexes are built once, outside the search, and the offset is applied
    to the QUERY rather than to the points. Shifting the drawn cloud by
    `offset` and asking whether a reference point `r` is near it is the same
    question as asking whether the unshifted cloud is near `r - offset` — and
    the second form does not rebuild an index 169 times.
    """
    dx, dy = offset
    covered = sum(1 for x, y in reference if drawn_index.distance((x - dx, y - dy)) <= TOLERANCE)
    coverage = covered / len(reference)

    distances = [reference_index.distance((x + dx, y + dy)) for x, y in drawn]
    mean_distance = sum(distances) / len(distances)
    outside_ratio = sum(1 for value in distances if value > TOLERANCE) / len(distances)
    return coverage, mean_distance, outside_ratio


def _length_penalty(ratio: float) -> float:
    """1.0 inside the band, falling linearly to 0 outside it."""
    if LENGTH_RATIO_MIN <= ratio <= LENGTH_RATIO_MAX:
        return 1.0
    if ratio < LENGTH_RATIO_MIN:
        # SQUARED, and the square is load-bearing. A compact glyph — م is a ring
        # 0.14 across with a short tail — has most of its reference within the
        # 0.10 tolerance of its own first half, so a half-drawn م measures
        # coverage 0.86 and a linear penalty passes it at 0.68. Squaring the
        # shortfall takes the same drawing to 0.53, which is the FAIL the
        # specification's test table requires for a partial letter. Above
        # LENGTH_RATIO_MIN nothing changes, so it costs a complete trace
        # nothing.
        return max(0.0, (ratio / LENGTH_RATIO_MIN) ** 2)
    excess = ratio - LENGTH_RATIO_MAX
    return max(0.0, 1.0 - LENGTH_PENALTY_SLOPE * excess / LENGTH_RATIO_MAX)


def evaluate_drawing(
    strokes: Path,
    reference: Path,
    *,
    width: float,
    height: float,
    threshold: float = PASS_THRESHOLD,
) -> DrawingResult:
    """Score one tracing attempt against one reference path.

    Returns 0.0 for anything that is not an attempt — no strokes at all, a
    single dot, a flick — rather than raising, because a child who lifted their
    finger too early has not caused an error, and the session has to carry on.
    """

    def _rejected(
        reason: str,
        *,
        mean_distance: float = 1.0,
        length_ratio: float = 0.0,
        sampled_points: int = 0,
    ) -> DrawingMetrics:
        """A metrics row for a submission that was refused before scoring.

        Coverage 0 and outside-ratio 1 rather than "unknown": the numbers are
        rendered in the caregiver console and in the AI inspector, and a blank
        there would read as a measurement that failed rather than as a canvas
        with nothing on it.
        """
        return DrawingMetrics(
            coverage=0.0,
            mean_distance=mean_distance,
            outside_ratio=1.0,
            length_ratio=length_ratio,
            sampled_points=sampled_points,
            rejected=reason,
        )

    reference_unit = [[(float(x), float(y)) for x, y in stroke] for stroke in reference if stroke]
    reference_points = resample(reference_unit)
    if not reference_points:
        # No reference means nothing can be scored. Failing closed is right: the
        # alternative is passing every child on a skill with no guide drawn.
        return DrawingResult(0.0, threshold, False, _rejected("no_reference"))

    drawn_unit = [smooth(stroke) for stroke in _to_unit_box(strokes, width=width, height=height)]
    drawn_points = resample(drawn_unit)
    drawn_length = path_length(drawn_unit)

    if not drawn_points:
        return DrawingResult(0.0, threshold, False, _rejected("empty"))
    if drawn_length < MIN_DRAWN_LENGTH:
        # A dot, or two touching points. Reported separately from "empty"
        # because the child DID touch the screen, and the caregiver-facing
        # prompt for the two is different.
        return DrawingResult(
            0.0,
            threshold,
            False,
            _rejected(
                "too_short",
                mean_distance=_nearest_distance(drawn_points[0], reference_points),
                length_ratio=drawn_length / max(path_length(reference_unit), 1e-9),
                sampled_points=len(drawn_points),
            ),
        )

    # The bounded translation search. Deterministic: a fixed grid walked in a
    # fixed order, and the first best wins, so the same strokes always produce
    # the same offset and therefore the same score.
    reference_index = _Nearest(reference_points)
    drawn_index = _Nearest(drawn_points)
    steps = round(TRANSLATION_LIMIT / TRANSLATION_STEP)
    best: tuple[float, float, float] | None = None
    best_key = -1.0
    for ix in range(-steps, steps + 1):
        for iy in range(-steps, steps + 1):
            offset = (ix * TRANSLATION_STEP, iy * TRANSLATION_STEP)
            coverage, mean_distance, outside = _measure(
                drawn_points,
                reference_points,
                drawn_index=drawn_index,
                reference_index=reference_index,
                offset=offset,
            )
            key = coverage * (1.0 - outside)
            if key > best_key:
                best_key = key
                best = (coverage, mean_distance, outside)

    assert best is not None
    coverage, mean_distance, outside_ratio = best

    length_ratio = drawn_length / max(path_length(reference_unit), 1e-9)
    score = coverage * (1.0 - outside_ratio) * _length_penalty(length_ratio)
    score = max(0.0, min(1.0, score))

    metrics = DrawingMetrics(
        coverage=coverage,
        mean_distance=mean_distance,
        outside_ratio=outside_ratio,
        length_ratio=length_ratio,
        sampled_points=len(drawn_points),
    )
    # `>=` and not `>`: the threshold is the pass mark, and a score exactly on
    # it passes. Asserted in the test table so the boundary is a decision rather
    # than an accident of which comparison someone typed.
    return DrawingResult(score, threshold, score >= threshold, metrics)


__all__ = [
    "MAX_REPORTED_DISTANCE",
    "MIN_DRAWN_LENGTH",
    "PASS_THRESHOLD",
    "TOLERANCE",
    "DrawingMetrics",
    "DrawingResult",
    "evaluate_drawing",
    "path_length",
    "resample",
    "smooth",
]
