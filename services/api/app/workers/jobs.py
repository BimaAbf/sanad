"""The job bodies `schedule.py` has been pointing at since P11.

`schedule.py` declares nine cron jobs as data and ends with "the job bodies live
in `app.workers.jobs`". That module did not exist, and neither did any runner --
so the notification policy, the nightly rollup backstop and BKT decay were nine
rows of configuration that nothing could execute. This is the half that runs.

**Three bodies, not nine, and the registry says which.** A job whose
dependencies are not built does not get a body that quietly does nothing; it is
absent from `JOB_BODIES`, and `run_job` refuses it by name and says what is
missing. That follows `cli.py`'s existing convention -- `just seed` and
`just eval` exited 1 with a message naming the P-prompt rather than pretending
to succeed -- and it is the difference between "the digest job is not built" and
"the digest job runs every Friday and sends nothing".

Each body takes an open `AsyncSession` and the current time, and returns a small
dict for the log line. Committing belongs to `run_job`, so a body that raises
half way leaves nothing behind.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.learning.repository import LearningRepository
from app.modules.learning.service import MasteryService
from app.modules.progress.history import ProgressHistory
from app.modules.progress.repository import ProgressRepository
from app.modules.progress.service import ProgressService
from app.workers.schedule import job_names

logger = structlog.get_logger(__name__)

JobBody = Callable[[AsyncSession, dt.datetime], Awaitable[Mapping[str, Any]]]


async def bkt_decay(session: AsyncSession, now: dt.datetime) -> Mapping[str, Any]:
    """Forgetting for skills past their review date (02:30 Cairo).

    The only thing in the product that moves `p_known` without an attempt, which
    is why it is a sweep rather than part of the session recompute -- that
    recompute is a function of the attempts and has to stay one.

    It can move a skill to `lapsed` and can never move one up. A caregiver whose
    child stopped practising three months ago should see that, not a `mastered`
    badge frozen at the moment they stopped.
    """
    service = MasteryService(repo=LearningRepository(session))
    touched = await service.decay_overdue(now=now)
    return {"rows": touched}


async def rollup_rebuild(session: AsyncSession, now: dt.datetime) -> Mapping[str, Any]:
    """Full rollup rebuild from `events` (02:00 Cairo). The correctness backstop.

    `ProgressService` deliberately runs one `compute()` for both the incremental
    path and this one, so the two CAN disagree -- and this job is what makes a
    disagreement get corrected rather than persist. Recomputing from the event
    log means a rollup that drifted for any reason is repaired overnight.

    Partitions are ensured first and in the same job. `events` is RANGE
    partitioned by month, so a missing partition is not slow -- it is every
    event insert failing, which would take the dashboard down for everybody at
    once on the first of a month.
    """
    store = ProgressRepository(session)
    partitions = await store.ensure_partitions(today=now.date())

    service = ProgressService(store=store, history=ProgressHistory(session))
    children = await store.rollup_children()
    rebuilt = 0
    for child_id in children:
        await service.rebuild_nightly(child_id=child_id)
        rebuilt += 1
    return {"children": rebuilt, "partitions": len(partitions)}


#: Only the jobs with a real body. Everything else in `schedule.JOBS` is
#: declared and unbuilt, and `run_job` reports it that way.
JOB_BODIES: dict[str, JobBody] = {
    "bkt_decay": bkt_decay,
    "rollup_rebuild": rollup_rebuild,
}

#: Why each declared job has no body yet. Named rather than blank so the refusal
#: tells an operator what is missing instead of only that something is.
UNBUILT: dict[str, str] = {
    "pgee_due_scan": "needs the notification send path: `notifications` has no writer",
    "weekly_digest": "needs the notification send path",
    "streak_encourage": "needs the notification send path",
    "report_ready": "event-driven; needs the report route, which is not built",
    "escalation_sla": "needs the escalations table and the clinician rota (O2)",
    "tts_pregen": "event-driven; needs the VoxCPM2 renderer, which does not exist",
    "cost_report": "needs per-child AI spend accounting, which is not recorded",
}


def unbuilt_jobs() -> list[str]:
    """Declared in `schedule.JOBS` and not runnable. Sorted, for a stable report."""
    return sorted(name for name in job_names() if name not in JOB_BODIES)


async def run_job(session: AsyncSession, name: str, *, now: dt.datetime) -> Mapping[str, Any]:
    """Dispatch one job by name. Raises `KeyError` for anything unrunnable.

    Committing is here rather than in the bodies so that a body which raises
    part way through leaves the database untouched -- a half-applied decay sweep
    is worse than one that did not run, because the next run would compute its
    overdue days from a date that was already partly advanced.
    """
    body = JOB_BODIES.get(name)
    if body is None:
        if name in UNBUILT:
            raise KeyError(f"job '{name}' is declared but not built: {UNBUILT[name]}")
        raise KeyError(f"unknown job '{name}'. Known: {', '.join(sorted(JOB_BODIES))}")

    result = await body(session, now)
    await session.commit()
    logger.info("job_ran", job=name)
    return result


__all__ = [
    "JOB_BODIES",
    "UNBUILT",
    "bkt_decay",
    "rollup_rebuild",
    "run_job",
    "unbuilt_jobs",
]
