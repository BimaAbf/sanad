"""The job registry.

The structural test here is `test_every_declared_job_is_either_built_or_named`.
`schedule.py` declared nine jobs and `app.workers.jobs` did not exist, so for
the whole of P11 the cadences were configuration nothing could execute. The
failure mode that replaces it -- a job with a body that quietly does nothing --
is worse, because it looks like it ran. This asserts the third option: every
declared job either runs or refuses by name with a reason.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.workers.jobs import JOB_BODIES, UNBUILT, run_job, unbuilt_jobs
from app.workers.schedule import job_names

NOW = dt.datetime(2026, 3, 1, 2, 30, tzinfo=dt.UTC)


def test_every_declared_job_is_either_built_or_named() -> None:
    """No job may be silently absent from both maps.

    Adding a `CronJob` to `schedule.JOBS` without either writing its body or
    saying what it is waiting for fails here, which is the point: the gap this
    file exists to close was exactly that kind of silence.
    """
    declared = set(job_names())
    accounted = set(JOB_BODIES) | set(UNBUILT)
    assert declared - accounted == set(), "a declared job with no body and no stated reason"
    assert accounted - declared == set(), "a body or excuse for a job nobody schedules"


def test_a_job_is_not_both_built_and_unbuilt() -> None:
    assert set(JOB_BODIES) & set(UNBUILT) == set()


def test_unbuilt_jobs_is_the_complement_of_the_registry() -> None:
    assert unbuilt_jobs() == sorted(set(job_names()) - set(JOB_BODIES))


def test_the_two_jobs_whose_dependencies_exist_are_built() -> None:
    """Named explicitly so removing one is a deliberate act, not a refactor."""
    assert set(JOB_BODIES) == {"bkt_decay", "rollup_rebuild"}


async def test_an_unbuilt_job_refuses_and_says_what_is_missing() -> None:
    """A refusal an operator can act on beats one that only says no."""
    with pytest.raises(KeyError) as refused:
        await run_job(_no_session(), "weekly_digest", now=NOW)
    assert "declared but not built" in refused.value.args[0]
    assert "notification send path" in refused.value.args[0]


async def test_an_unknown_job_lists_the_ones_that_exist() -> None:
    with pytest.raises(KeyError) as refused:
        await run_job(_no_session(), "not_a_job", now=NOW)
    assert "unknown job" in refused.value.args[0]
    assert "bkt_decay" in refused.value.args[0]


def _no_session() -> object:
    """Both refusals happen before the session is touched, so there is nothing
    to fake. Passing an object that would raise on any use asserts that."""

    class Unusable:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"run_job touched the session ({name}) before refusing")

    return Unusable()
