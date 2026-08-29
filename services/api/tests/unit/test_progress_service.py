"""T10 — the service layer, and the whole-schema norm guard.

`test_no_endpoint_anywhere_exposes_a_norm` walks the entire generated OpenAPI
document rather than the progress schemas alone. docs/04a §C09 forbids a
percentile or a DQ on a *dashboard*, and the way that rule dies is that someone
adds a perfectly reasonable field to a different module a year from now.
"""

from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import uuid4

import pytest

from app.modules.progress.domain.rollup import Rollup, SessionFact, SkillStateFact
from app.modules.progress.domain.views import Activity, AssessmentPoint
from app.modules.progress.schemas import (
    MAX_EVENTS_PER_BATCH,
    AssessmentSummary,
    EventBatch,
    EventIn,
)
from app.modules.progress.service import ProgressService

NOW = dt.datetime(2026, 8, 29, 10, 0, tzinfo=dt.UTC)


class FakeStore:
    def __init__(self, *, duplicates: int = 0) -> None:
        self.events: list[dict[str, object]] = []
        self.rollups_written: list[Rollup] = []
        self.duplicates = duplicates
        self.cards: list[dict[str, object]] = []
        self._rollups: list[dict[str, object]] = []

    async def record_events(self, rows: Any) -> int:
        self.events.extend(rows)
        return max(0, len(rows) - self.duplicates)

    async def upsert_rollups(self, rollups: Any) -> None:
        # Upsert semantics: last write per key wins, which is what the SQL does.
        index = {rollup.key(): rollup for rollup in self.rollups_written}
        for rollup in rollups:
            index[rollup.key()] = rollup
        self.rollups_written = list(index.values())

    async def rollups(self, child_id: str, *, pattern: str = "%") -> list[dict[str, object]]:
        return self._rollups

    async def skill_cards(self, child_id: str) -> list[dict[str, object]]:
        return self.cards

    def seed_rollup(self, period: str, **fields: object) -> None:
        row: dict[str, object] = {
            "child_id": "c1",
            "period": period,
            "sessions": 1,
            "minutes": 8,
            "attempts": 10,
            "accuracy": 0.7,
            "skills_mastered": 3,
            "skills_practising": 2,
            "by_category": {},
        }
        row.update(fields)
        self._rollups.append(row)


class FakeHistory:
    def __init__(
        self,
        *,
        sessions: list[SessionFact] | None = None,
        points: list[AssessmentPoint] | None = None,
        candidates: list[Activity] | None = None,
        suggestion: Activity | None = None,
    ) -> None:
        self._sessions = sessions or []
        self._points = points or []
        self._candidates = candidates or []
        self._suggestion = suggestion

    async def sessions(self, child_id: str) -> list[SessionFact]:
        return self._sessions

    async def skill_states(self, child_id: str) -> list[SkillStateFact]:
        return [SkillStateFact("k1", "colors", "mastered")]

    async def assessment_points(self, child_id: str) -> list[AssessmentPoint]:
        return self._points

    async def assessment_summaries(self, child_id: str) -> list[AssessmentSummary]:
        return [
            AssessmentSummary(
                assessment_id="a1", status="completed", started_at=NOW, report_available=True
            )
        ]

    async def revisit_candidates(self, child_id: str) -> list[Activity]:
        return self._candidates

    async def suggestion(self, child_id: str) -> Activity | None:
        return self._suggestion


def event(key: str) -> EventIn:
    return EventIn(
        name="play.activity.shown",
        props={"activity_id": "x"},
        client_ts=NOW,
        idempotency_key=key,
    )


# --- ingestion -------------------------------------------------------------


async def test_ingestion_reports_duplicates_rather_than_failing() -> None:
    """An outbox drain replays by design; a replay is not an error."""
    store = FakeStore(duplicates=2)
    service = ProgressService(store=store, history=FakeHistory())
    batch = EventBatch(events=[event(f"k{index:08d}") for index in range(5)])

    accepted = await service.ingest(caregiver_id=uuid4(), batch=batch)
    assert accepted == 3
    assert len(store.events) == 5


async def test_events_carry_the_caregiver_and_serialised_props() -> None:
    store = FakeStore()
    service = ProgressService(store=store, history=FakeHistory())
    caregiver = uuid4()
    await service.ingest(caregiver_id=caregiver, batch=EventBatch(events=[event("k" * 10)]))
    row = store.events[0]
    assert row["caregiver_id"] == str(caregiver)
    assert isinstance(row["props"], str)


def test_a_batch_is_bounded() -> None:
    """An unbounded batch is a memory-exhaustion vector on a public endpoint."""
    with pytest.raises(ValueError):
        EventBatch(events=[event(f"k{index:08d}") for index in range(MAX_EVENTS_PER_BATCH + 1)])
    with pytest.raises(ValueError):
        EventBatch(events=[])


def test_an_event_without_an_idempotency_key_is_rejected() -> None:
    with pytest.raises(ValueError):
        EventIn(name="x", client_ts=NOW, idempotency_key="short")


# --- rollup paths ----------------------------------------------------------


def session(offset: int) -> SessionFact:
    return SessionFact(
        session_id=f"s{offset}",
        child_id="c1",
        started_at=NOW - dt.timedelta(days=offset),
        minutes=8,
        attempts=10,
        correct=7,
        by_category={"colors": 10},
    )


async def test_session_end_writes_only_the_affected_periods() -> None:
    history = FakeHistory(sessions=[session(0), session(5)])
    service = ProgressService(store=FakeStore(), history=history)
    written = await service.rollup_on_session_end(child_id="c1", session=session(0))
    assert {rollup.period for rollup in written} == {
        "day:2026-08-29",
        "week:2026-W35",
        "all",
    }


async def test_nightly_rebuild_writes_every_period() -> None:
    history = FakeHistory(sessions=[session(0), session(40)])
    store = FakeStore()
    service = ProgressService(store=store, history=history)
    written = await service.rebuild_nightly(child_id="c1")
    # Two distinct days, two distinct weeks, plus all-time.
    assert len(written) == 5
    assert len(store.rollups_written) == 5


# --- views -----------------------------------------------------------------


async def test_today_reads_from_rollups_not_from_raw_sessions() -> None:
    store = FakeStore()
    store.seed_rollup("day:2026-08-29", sessions=2, minutes=16, attempts=20)
    store.seed_rollup("day:2026-08-28")
    service = ProgressService(
        store=store,
        history=FakeHistory(suggestion=Activity("listen_point_2choice", "k1", "أحمر")),
    )
    response = await service.today("c1", today=NOW)
    assert response.date == "2026-08-29"
    assert response.sessions == 2
    assert response.attempts == 20
    assert response.streak_days == 2
    assert response.suggestion is not None
    assert response.suggestion.label_ar == "أحمر"


async def test_today_surfaces_a_regression_with_its_plan() -> None:
    store = FakeStore()
    store.seed_rollup("day:2026-08-28", skills_mastered=5)
    store.seed_rollup("day:2026-08-29", skills_mastered=4)
    candidates = [Activity("a", f"k{index}", f"l{index}") for index in range(4)]
    service = ProgressService(store=store, history=FakeHistory(candidates=candidates))
    response = await service.today("c1", today=NOW)
    assert response.regression_detected
    assert len(response.revisit_plan) == 3


async def test_skills_view_defaults_a_never_seen_skill_to_not_started() -> None:
    store = FakeStore()
    store.cards = [
        {
            "skill_id": "1",
            "code": "color_red",
            "label_ar": "أحمر",
            "category": "colors",
            "state": None,
            "p_known": None,
            "due_at": None,
            "last_seen_at": None,
        }
    ]
    service = ProgressService(store=store, history=FakeHistory())
    response = await service.skills("c1")
    assert response.not_started == 1
    assert response.by_category["colors"][0].state == "not_started"
    assert response.by_category["colors"][0].p_known == 0.0


async def test_journey_is_insufficient_data_with_two_assessments() -> None:
    points = [
        AssessmentPoint("a1", dt.date(2026, 1, 1), {"motor": 20.0}, 3),
        AssessmentPoint("a2", dt.date(2026, 6, 1), {"motor": 22.0}, 5),
    ]
    service = ProgressService(store=FakeStore(), history=FakeHistory(points=points))
    response = await service.journey("c1")
    assert response.status == "insufficient_data"
    assert response.points == []
    assert response.copy_key


async def test_journey_returns_points_with_three_assessments() -> None:
    points = [
        AssessmentPoint(
            f"a{index}",
            dt.date(2025, 1, 1) + dt.timedelta(days=180 * index),
            {"motor": 20.0 + index},
            index,
        )
        for index in range(3)
    ]
    service = ProgressService(store=FakeStore(), history=FakeHistory(points=points))
    response = await service.journey("c1")
    assert response.status == "ok"
    assert len(response.points) == 3


async def test_assessments_passes_through() -> None:
    service = ProgressService(store=FakeStore(), history=FakeHistory())
    summaries = await service.assessments("c1")
    assert summaries[0].assessment_id == "a1"


# --- the whole-schema guard ------------------------------------------------

#: Substrings that must not appear as a field name anywhere in the API. Broader
#: than the exact-name list, because `child_percentile` is the same mistake.
FORBIDDEN_SUBSTRINGS = ("percentile", "centile", "z_score", "norm_comparison", "peer_")

#: Exact names. `dq` is too short for a substring rule — it would match
#: `dq_anything` but also nothing useful, and it would not match `dq` inside a
#: longer legitimate word either way.
FORBIDDEN_EXACT = ("dq", "developmental_quotient", "rank")

#: Report payloads are explicitly allowed to carry DQ: docs/04a §C09 puts it
#: "only inside the report, in context, behind the opt-in norm panel".
REPORT_SCHEMAS = ("AssessmentReport", "ReportPayload", "NormPanel")


def _walk(node: Any, path: str = "") -> list[tuple[str, str]]:
    """Every (schema path, property name) in the document."""
    found: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "properties" and isinstance(value, dict):
                found.extend((path, name) for name in value)
            found.extend(_walk(value, f"{path}/{key}" if path else str(key)))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            found.extend(_walk(item, f"{path}[{index}]"))
    return found


def test_no_endpoint_anywhere_exposes_a_norm() -> None:
    """T10 §3 — inspect the ENTIRE generated OpenAPI schema."""
    from app.main import app

    document = app.openapi()
    offenders: list[str] = []
    for path, name in _walk(document):
        if any(marker in path for marker in REPORT_SCHEMAS):
            continue
        lowered = name.lower()
        if lowered in FORBIDDEN_EXACT or any(marker in lowered for marker in FORBIDDEN_SUBSTRINGS):
            offenders.append(f"{path}:{name}")
    assert offenders == [], offenders


def test_the_norm_guard_would_catch_a_violation() -> None:
    """The guard has to be able to fail, or it is decoration."""
    document = {"components": {"schemas": {"Bad": {"properties": {"percentile": {}}}}}}
    hits = [name for _, name in _walk(document) if "percentile" in name]
    assert hits == ["percentile"]


def _flatten(routes: Any) -> list[Any]:
    """Every APIRoute, including those inside an included router.

    This FastAPI version wraps `include_router` results in an `_IncludedRouter`
    node that keeps the real routes on `original_router`, rather than splicing
    them into `app.routes`. The first version of this test iterated
    `app.routes` directly, found zero child-scoped paths, and passed vacuously
    — which is exactly the failure mode a guard test has to be checked against,
    and why `test_the_child_access_guard_would_catch_an_unprotected_route`
    exists below.
    """
    flat: list[Any] = []
    for route in routes:
        nested = getattr(route, "routes", None)
        if nested is None:
            included = getattr(route, "original_router", None)
            nested = getattr(included, "routes", None) if included is not None else None
        if nested:
            flat.extend(_flatten(nested))
        else:
            flat.append(route)
    return flat


def test_every_child_scoped_route_declares_child_access() -> None:
    """docs/05 §9. The guard script checks this statically; this checks the
    live dependency graph, which is what actually runs."""
    from app.main import app
    from app.modules.identity.deps import require_child_access

    routes = _flatten(app.routes)
    child_scoped = [route for route in routes if "{child_id}" in getattr(route, "path", "")]
    # The guard is worthless if it inspects nothing.
    assert len(child_scoped) >= 5, "no child-scoped routes found; the guard is vacuous"

    unguarded = [
        route.path
        for route in child_scoped
        if require_child_access.__name__ not in _dependency_names(getattr(route, "dependant", None))
    ]
    assert unguarded == []


def test_the_child_access_guard_would_catch_an_unprotected_route() -> None:
    """Same shape as the real check, run against a deliberately naked route."""
    from fastapi import APIRouter, FastAPI
    from fastapi.routing import APIRoute

    from app.modules.identity.deps import require_child_access

    naked = APIRouter()

    @naked.get("/children/{child_id}/oops")
    async def oops(child_id: str) -> dict[str, str]:  # pragma: no cover - never called
        return {}

    probe = FastAPI()
    probe.include_router(naked)
    routes = [r for r in _flatten(probe.routes) if isinstance(r, APIRoute)]
    offenders = [
        r.path
        for r in routes
        if "{child_id}" in r.path
        and require_child_access.__name__ not in _dependency_names(r.dependant)
    ]
    assert offenders == ["/children/{child_id}/oops"]


def _dependency_names(dependant: Any) -> set[str]:
    if dependant is None:
        return set()
    names: set[str] = set()
    for sub in getattr(dependant, "dependencies", []):
        call = getattr(sub, "call", None)
        if call is not None:
            names.add(getattr(call, "__name__", ""))
            names.add(getattr(call, "__qualname__", "").split(".")[0])
        names |= _dependency_names(sub)
    return names
