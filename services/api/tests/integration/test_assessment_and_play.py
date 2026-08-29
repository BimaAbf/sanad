"""The two paths that separated "runs" from "usable", against a real database.

Both were unreachable by any unit test, and for the same reason: the defect was
that there was no SQL, and a test with a fake repository cannot notice missing
SQL. So this file uses real Postgres, real HTTP through the ASGI app, and a real
JWT, and it asserts the two end-to-end facts that were previously false:

* `test_three_assessments_turn_the_journey_from_insufficient_data_to_ok` —
  the journey view answered `insufficient_data` for every child forever, because
  `assessment_points` returned `[]` unconditionally. Three completed
  assessments now produce three points and `status: "ok"`. Two still produce
  `insufficient_data`, which is the docs/04a §C09 rule and is asserted here so a
  future change cannot quietly drop it.

* `test_an_attempt_survives_the_round_trip_and_a_replay_creates_no_duplicate` —
  `/play` posted attempts into an outbox whose sender was
  `async () => ({ok: true})`, so nothing was ever stored. The attempt is now a
  row, and re-posting the same idempotency key -- what the outbox does after a
  dropped connection -- adds nothing, which is the docs/04e §C13 acceptance
  criterion stated as a test rather than as prose.

Everything is rolled back. These tests seed children, caregivers and skills, and
leaving them behind would make the next run start from a different database.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import dispose_engine, get_session, init_engine
from app.core.redis import dispose_redis, init_redis
from app.main import create_app
from app.modules.identity.security import issue_access_token

pytestmark = pytest.mark.integration

INSERT_CAREGIVER = text("""
    INSERT INTO caregivers (id, phone_e164, display_name)
    VALUES (CAST(:id AS uuid), :phone, 'T')
""")

INSERT_CHILD = text("""
    INSERT INTO children (id, display_name, date_of_birth, comms_level, max_choices)
    VALUES (CAST(:id AS uuid), :name, DATE '2022-05-01', 'single_words', 2)
""")

LINK = text("""
    INSERT INTO caregiver_child (caregiver_id, child_id, role)
    VALUES (CAST(:caregiver_id AS uuid), CAST(:child_id AS uuid), 'owner')
""")

INSERT_SKILL = text("""
    INSERT INTO skills (
        code, category, label_ar, label_vowelised, label_egy,
        transliteration, phonemes, difficulty_tier, intro_order, alt_text_ar,
        prerequisites
    ) VALUES (
        :code, CAST(:category AS skill_category), :label_ar, :label_ar, :label_ar,
        :code, :code, 1, :intro_order, :label_ar, '[]'::jsonb
    )
    ON CONFLICT (code) DO NOTHING
    RETURNING id
""")


@pytest.fixture
def settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
async def session(settings: Settings):  # type: ignore[no-untyped-def]
    """A session inside an outer transaction that is always rolled back.

    Not the obvious `get_session()` + `rollback()`. Every route in this file
    calls `session.commit()`, and a commit on a plain session ENDS the
    transaction -- so the teardown rollback has nothing left to undo and the
    rows stay in the database. The first version of this fixture did exactly
    that, and the symptom was the second run of the suite failing on a
    duplicate idempotency key left behind by the first.

    Binding the session to a connection that already has a transaction open,
    with `join_transaction_mode="create_savepoint"`, turns each route commit
    into a savepoint release. Rolling back the outer transaction at the end
    undoes all of them.
    """
    engine = init_engine(settings)
    # Redis too: `get_identity_service` builds a RateLimiter over it, and every
    # authenticated route in this file resolves that dependency.
    init_redis(settings)
    async with engine.connect() as connection:
        outer = await connection.begin()
        active = AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield active
        finally:
            await active.close()
            await outer.rollback()
    await dispose_engine()
    await dispose_redis()


@pytest.fixture
async def client(settings: Settings, session):  # type: ignore[no-untyped-def]
    """The real app, with `get_session` pinned to the test's transaction.

    Pinning is what makes rollback possible: the routes call `session.commit()`,
    and against an independent session that would leave rows behind. Overriding
    the dependency means every route writes into the transaction this fixture
    owns and rolls back at the end.
    """
    app = create_app(settings)

    async def _session_override():  # type: ignore[no-untyped-def]
        yield session

    app.dependency_overrides[get_session] = _session_override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


async def _seed_family(session) -> tuple[str, str, dict[str, str]]:  # type: ignore[no-untyped-def]
    caregiver_id = str(uuid.uuid4())
    child_id = str(uuid.uuid4())
    suffix = caregiver_id.replace("-", "")[:9]
    await session.execute(INSERT_CAREGIVER, {"id": caregiver_id, "phone": f"+2011{suffix}"})
    await session.execute(INSERT_CHILD, {"id": child_id, "name": "تجربة"})
    await session.execute(LINK, {"caregiver_id": caregiver_id, "child_id": child_id})
    token, _ = issue_access_token(caregiver_id=uuid.UUID(caregiver_id))
    return caregiver_id, child_id, {"Authorization": f"Bearer {token}"}


async def _seed_skills(session) -> None:  # type: ignore[no-untyped-def]
    """Two colours, so a two-choice activity has a real distractor."""
    for order, (code, label) in enumerate([("color_red", "أحمر"), ("color_blue", "أزرق")], start=1):
        await session.execute(
            INSERT_SKILL,
            {"code": code, "category": "colors", "label_ar": label, "intro_order": order},
        )


async def _complete_one_assessment(client: AsyncClient, headers: dict[str, str], child_id: str):
    """Start, answer until the engine stops asking, finalise."""
    started = await client.post("/assessments", json={"child_id": child_id}, headers=headers)
    assert started.status_code == 201, started.text
    state: dict[str, Any] = started.json()
    assessment_id = state["assessment_id"]

    # Bounded: the synthetic bank is 120 items and evidence propagation credits
    # many of them per answer. An unbounded loop here would hang the suite if
    # the engine ever stopped converging, which is itself worth failing on.
    for _ in range(200):
        if state["complete"] or not state["next_items"]:
            break
        item = state["next_items"][0]
        answered = await client.post(
            f"/assessments/{assessment_id}/answers",
            json={"item_id": item["item_id"], "verdict": "yes"},
            headers=headers,
        )
        assert answered.status_code == 200, answered.text
        state = answered.json()

    scored = await client.post(f"/assessments/{assessment_id}/finalise", headers=headers)
    assert scored.status_code == 200, scored.text
    return scored.json()


async def test_an_assessment_persists_its_answers_and_scores_every_domain(
    client: AsyncClient, session
) -> None:  # type: ignore[no-untyped-def]
    _, child_id, headers = await _seed_family(session)

    result = await _complete_one_assessment(client, headers, child_id)

    assert result["status"] == "completed"
    # Six domains in the synthetic bank; every one scored.
    assert len(result["domain_da"]) == 6
    assert all(value >= 0 for value in result["domain_da"].values())

    # The answers are rows, which is the whole point. Observed and propagated
    # both, and the log is append-only so nothing was overwritten.
    stored = (
        await session.execute(
            text(
                "SELECT count(*) AS n FROM assessment_answers "
                "WHERE assessment_id = CAST(:a AS uuid)"
            ),
            {"a": result["assessment_id"]},
        )
    ).one()
    assert stored.n > 0


async def test_answering_the_same_item_twice_is_a_correction_not_a_duplicate(
    client: AsyncClient, session
) -> None:  # type: ignore[no-untyped-def]
    _, child_id, headers = await _seed_family(session)
    started = await client.post("/assessments", json={"child_id": child_id}, headers=headers)
    assessment_id = started.json()["assessment_id"]
    item = started.json()["next_items"][0]["item_id"]

    await client.post(
        f"/assessments/{assessment_id}/answers",
        json={"item_id": item, "verdict": "yes"},
        headers=headers,
    )
    await client.post(
        f"/assessments/{assessment_id}/answers",
        json={"item_id": item, "verdict": "no"},
        headers=headers,
    )

    live = (
        await session.execute(
            text(
                "SELECT verdict::text AS verdict FROM assessment_answers "
                "WHERE assessment_id = CAST(:a AS uuid) AND item_id = :i "
                "AND superseded_at IS NULL"
            ),
            {"a": assessment_id, "i": item},
        )
    ).all()
    # Exactly one live answer, and it is the correction. The superseded row is
    # still on file — the ledger is the audit.
    assert [row.verdict for row in live] == ["no"]

    superseded = (
        await session.execute(
            text(
                "SELECT count(*) AS n FROM assessment_answers "
                "WHERE assessment_id = CAST(:a AS uuid) AND item_id = :i "
                "AND superseded_at IS NOT NULL"
            ),
            {"a": assessment_id, "i": item},
        )
    ).one()
    assert superseded.n == 1


async def test_the_same_idempotency_key_twice_records_one_answer(
    client: AsyncClient, session
) -> None:  # type: ignore[no-untyped-def]
    _, child_id, headers = await _seed_family(session)
    started = await client.post("/assessments", json={"child_id": child_id}, headers=headers)
    assessment_id = started.json()["assessment_id"]
    item = started.json()["next_items"][0]["item_id"]
    keyed = {**headers, "Idempotency-Key": "retry-after-a-timeout"}

    first = await client.post(
        f"/assessments/{assessment_id}/answers",
        json={"item_id": item, "verdict": "yes"},
        headers=keyed,
    )
    second = await client.post(
        f"/assessments/{assessment_id}/answers",
        json={"item_id": item, "verdict": "yes"},
        headers=keyed,
    )

    assert first.status_code == second.status_code == 200
    # The retry changed nothing: same answered count, not one more.
    assert first.json()["answered"] == second.json()["answered"]


async def test_three_assessments_turn_the_journey_from_insufficient_data_to_ok(
    client: AsyncClient, session
) -> None:  # type: ignore[no-untyped-def]
    """The defect this whole migration exists for. docs/04a §C09."""
    _, child_id, headers = await _seed_family(session)

    for completed in range(1, 4):
        await _complete_one_assessment(client, headers, child_id)
        journey = await client.get(f"/children/{child_id}/progress/journey", headers=headers)
        assert journey.status_code == 200, journey.text
        body = journey.json()
        if completed < 3:
            # Two points is not a trend. Showing one to an anxious parent is
            # telling them something untrue about their child.
            assert body["status"] == "insufficient_data"
        else:
            assert body["status"] == "ok"
            assert len(body["points"]) == 3
            assert all(point["domain_da"] for point in body["points"])


async def test_the_assessment_list_shows_every_administration(client: AsyncClient, session) -> None:  # type: ignore[no-untyped-def]
    _, child_id, headers = await _seed_family(session)
    await _complete_one_assessment(client, headers, child_id)

    listed = await client.get(f"/children/{child_id}/progress/assessments", headers=headers)
    assert listed.status_code == 200
    assert [row["status"] for row in listed.json()] == ["completed"]


# --- play -------------------------------------------------------------------


async def test_a_play_session_returns_a_real_plan(client: AsyncClient, session) -> None:  # type: ignore[no-untyped-def]
    _, child_id, headers = await _seed_family(session)
    await _seed_skills(session)

    created = await client.post(
        "/play/sessions", json={"child_id": child_id, "minutes": 3}, headers=headers
    )
    assert created.status_code == 201, created.text
    body = created.json()

    assert body["plan_source"] == "deterministic_fallback"
    assert body["activities"], "a session with no activities renders as an instant closing scene"
    first = body["activities"][0]
    # Two choices, exactly one of them correct, and the distractor is a real
    # discrimination rather than a giveaway from another category.
    assert len(first["choices"]) == 2
    assert sum(1 for choice in first["choices"] if choice["correct"]) == 1
    assert all(choice["alt_ar"] for choice in first["choices"])


async def test_an_attempt_survives_the_round_trip_and_a_replay_creates_no_duplicate(
    client: AsyncClient, session
) -> None:  # type: ignore[no-untyped-def]
    """docs/04e §C13: a dropout loses zero attempts and creates zero duplicates."""
    _, child_id, headers = await _seed_family(session)
    await _seed_skills(session)
    created = (
        await client.post("/play/sessions", json={"child_id": child_id}, headers=headers)
    ).json()
    session_id = created["session_id"]
    activity = created["activities"][0]

    body = {
        "activity_code": activity["activity_code"],
        "skill_code": activity["skill_code"],
        "result": "correct",
        "prompt_level": "independent",
        "selected_skill_code": activity["skill_code"],
        "latency_ms": 2400,
        "choice_count": 2,
        "idempotency_key": "attempt-0001-stable",
    }

    first = await client.post(f"/play/sessions/{session_id}/attempts", json=body, headers=headers)
    assert first.status_code == 202, first.text
    assert first.json() == {"accepted": 1, "duplicates": 0}

    # The outbox drain after a 30-second dropout: same key, same body.
    replay = await client.post(f"/play/sessions/{session_id}/attempts", json=body, headers=headers)
    assert replay.json() == {"accepted": 0, "duplicates": 1}

    rows = (
        await session.execute(
            text("SELECT count(*) AS n FROM attempts WHERE session_id = CAST(:s AS uuid)"),
            {"s": session_id},
        )
    ).one()
    assert rows.n == 1


async def test_ending_a_session_reaches_the_caregiver_dashboard(
    client: AsyncClient, session
) -> None:  # type: ignore[no-untyped-def]
    """The other half of "usable": a session the caregiver can actually see."""
    _, child_id, headers = await _seed_family(session)
    await _seed_skills(session)
    created = (
        await client.post("/play/sessions", json={"child_id": child_id}, headers=headers)
    ).json()
    session_id = created["session_id"]
    activity = created["activities"][0]

    await client.post(
        f"/play/sessions/{session_id}/attempts/batch",
        json={
            "attempts": [
                {
                    "activity_code": activity["activity_code"],
                    "skill_code": activity["skill_code"],
                    "result": "correct",
                    "idempotency_key": f"batch-attempt-{n:04d}",
                }
                for n in range(3)
            ]
        },
        headers=headers,
    )

    ended = await client.post(
        f"/play/sessions/{session_id}/end",
        json={"reason": "completed", "minutes": 6},
        headers=headers,
    )
    assert ended.status_code == 200, ended.text
    assert ended.json()["activities_done"] == 3
    assert ended.json()["correct_count"] == 3

    today = await client.get(f"/children/{child_id}/progress/today", headers=headers)
    assert today.status_code == 200, today.text
    # Before this, `today` was zeros for every child forever: no `session_end`
    # event was ever written, so the rollup had nothing to roll up.
    assert today.json()["sessions"] == 1
    assert today.json()["minutes"] == 6
    assert today.json()["attempts"] == 3


async def test_a_caregiver_cannot_touch_another_familys_session(
    client: AsyncClient, session
) -> None:  # type: ignore[no-untyped-def]
    """These paths carry no `{child_id}`, so GUARD 1 cannot check them."""
    _, child_id, headers = await _seed_family(session)
    await _seed_skills(session)
    created = (
        await client.post("/play/sessions", json={"child_id": child_id}, headers=headers)
    ).json()

    _, _, stranger = await _seed_family(session)
    refused = await client.post(
        f"/play/sessions/{created['session_id']}/end",
        json={"reason": "completed", "minutes": 1},
        headers=stranger,
    )
    assert refused.status_code == 403


async def test_a_stranger_cannot_read_an_assessment(client: AsyncClient, session) -> None:  # type: ignore[no-untyped-def]
    _, child_id, headers = await _seed_family(session)
    started = (
        await client.post("/assessments", json={"child_id": child_id}, headers=headers)
    ).json()

    _, _, stranger = await _seed_family(session)
    refused = await client.get(f"/assessments/{started['assessment_id']}", headers=stranger)
    assert refused.status_code == 403
