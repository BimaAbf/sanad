"""Period keys for `progress_rollups`.

docs/02 §8 fixes the shape: `day:2026-08-29`, `week:2026-W35`, `all`. Two things
about them that are easy to get wrong and expensive to get wrong:

* **The day is the family's civil day, not UTC.** Cairo is UTC+2/+3, so a
  session at 01:00 local would otherwise be rolled into yesterday and a streak
  would break for a family that did nothing wrong.
* **The week is ISO.** Egypt's working week starts on Saturday, but the rollup
  key is an identifier, not a presentation choice; the caregiver app labels the
  week however it likes. Mixing the two produces two keys for one week and the
  nightly rebuild then silently disagrees with the incremental path.

Pure. No I/O.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

PRODUCT_TZ = ZoneInfo("Africa/Cairo")

ALL_TIME = "all"


def local_date(moment: dt.datetime) -> dt.date:
    """The civil date in Cairo for an instant.

    A naive datetime is treated as UTC rather than as local time: everything
    that reaches here comes from a `timestamptz` column or a client clock, and
    guessing "local" for a naive value is how an off-by-one-day bug gets in.
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.UTC)
    return moment.astimezone(PRODUCT_TZ).date()


def day_key(value: dt.date | dt.datetime) -> str:
    if isinstance(value, dt.datetime):
        value = local_date(value)
    return f"day:{value.isoformat()}"


def week_key(value: dt.date | dt.datetime) -> str:
    if isinstance(value, dt.datetime):
        value = local_date(value)
    year, week, _ = value.isocalendar()
    return f"week:{year}-W{week:02d}"


def periods_for(moment: dt.datetime) -> tuple[str, str, str]:
    """Every period one event contributes to."""
    date = local_date(moment)
    return day_key(date), week_key(date), ALL_TIME


def parse_day(key: str) -> dt.date:
    return dt.date.fromisoformat(key.removeprefix("day:"))


def month_key(value: dt.date) -> str:
    """The `events` partition an instant belongs to. docs/02 §9: monthly."""
    return f"{value.year:04d}_{value.month:02d}"


def next_month(value: dt.date) -> dt.date:
    """First day of the following month."""
    if value.month == 12:
        return dt.date(value.year + 1, 1, 1)
    return dt.date(value.year, value.month + 1, 1)


def partition_bounds(value: dt.date) -> tuple[dt.date, dt.date]:
    start = value.replace(day=1)
    return start, next_month(start)
