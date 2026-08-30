"""The nine cron jobs, as data.

docs/04a §C10 gives a table of jobs and cadences. It is transcribed here as a
declarative list rather than as nine decorated functions, for one reason: the
cadences are stated in **Africa/Cairo local time**, and the thing that will
actually go wrong is a job written to a UTC hour that drifts by one twice a
year when Egypt changes clocks.

Keeping the schedule as data means the local-to-UTC conversion happens in one
tested function instead of nine hand-written constants.

Pure. The job bodies live in `app.workers.jobs`; this file only says when.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from zoneinfo import ZoneInfo

PRODUCT_TZ = ZoneInfo("Africa/Cairo")


@dataclass(frozen=True, slots=True)
class CronJob:
    name: str
    #: Local hour and minute in Africa/Cairo. None means event-driven.
    local_hour: int | None
    local_minute: int = 0
    #: ISO weekday (1=Monday) or None for daily.
    weekday: int | None = None
    event_driven: bool = False
    note: str = ""


#: docs/04a §C10, verbatim in content and order.
JOBS: tuple[CronJob, ...] = (
    CronJob("pgee_due_scan", 9, note="nudge at 180, 194, 208 days then stop forever"),
    CronJob("weekly_digest", 18, weekday=5, note="Fridays; only if >= 1 session that week"),
    CronJob("streak_encourage", 17, note="only if played yesterday but not today, opt-in"),
    CronJob("report_ready", None, event_driven=True, note="push + in-app"),
    CronJob("escalation_sla", None, local_minute=0, note="hourly"),
    CronJob("rollup_rebuild", 2, note="full rebuild; the correctness backstop"),
    CronJob("bkt_decay", 2, local_minute=30, note="forgetting for overdue skills"),
    CronJob("tts_pregen", None, event_driven=True, note="on content publish"),
    CronJob("cost_report", 7, note="per-child spend and budget breaches, to ops"),
)


def utc_hour_for(job: CronJob, *, on: dt.date) -> int | None:
    """The UTC hour that lands on `job.local_hour` in Cairo on a given date.

    Date-dependent on purpose. Egypt reintroduced DST in 2023, so the answer for
    the same job differs between January and July, and a constant would be wrong
    for roughly half the year.
    """
    if job.local_hour is None:
        return None
    local = dt.datetime.combine(on, dt.time(job.local_hour, job.local_minute), tzinfo=PRODUCT_TZ)
    return local.astimezone(dt.UTC).hour


def scheduled_jobs() -> Sequence[CronJob]:
    return JOBS


def job_names() -> tuple[str, ...]:
    return tuple(job.name for job in JOBS)
