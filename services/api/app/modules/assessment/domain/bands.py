"""Band arithmetic and age-equivalent interpolation.

`age_equivalent` is the function that turns a raw score into the number a
caregiver reads as "your child is at about 40 months in language". It is
deliberately linear interpolation inside a band: no smoothing, no IRT, no black
box. A clinician must be able to reproduce it on paper, because a clinician is
who has to defend it.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.modules.assessment.domain.state import Band

#: (band_id, cumulative_items_through_band, min_months, max_months)
CumulativeRow = tuple[int, int, int, int]


def band_for_months(bands: Sequence[Band], months: float) -> int:
    """The band a given age falls in, clamped to the bank's range.

    Clamping rather than raising: a child outside the bank's range still gets a
    developmental age, and `out_of_range` suppresses the quotient instead.
    """
    if not bands:
        raise ValueError("bank has no bands")
    for band in bands:
        if months < band.max_months:
            return band.id
    return bands[-1].id


def entry_band(bands: Sequence[Band], months: float, offset: int) -> int:
    """Where to start administering, clamped to the bank.

    The offset is negative (default -1): start a band below the child's age so
    the basal run has somewhere to form.
    """
    lo = min(b.id for b in bands)
    hi = max(b.id for b in bands)
    return max(lo, min(hi, band_for_months(bands, months) + offset))


def age_equivalent(raw: float, cumulative: Sequence[CumulativeRow]) -> float:
    """Interpolate a raw score into months.

    Transcribed from docs/04b §C03. `raw` lands inside the first band whose
    cumulative item count reaches it; the position within that band is linear.

    A raw score at or beyond the top of the bank returns the top of the last
    band — the bank cannot measure higher than it reaches, and pretending
    otherwise would be an extrapolation a clinician could not defend.
    """
    if not cumulative:
        return 0.0
    prev_cum = 0
    prev_max = 0
    for _band, cum, lo, hi in cumulative:
        if raw <= cum:
            span = cum - prev_cum
            frac = (raw - prev_cum) / span if span else 0.0
            return lo + frac * (hi - lo)
        prev_cum, prev_max = cum, hi
    return float(prev_max)
