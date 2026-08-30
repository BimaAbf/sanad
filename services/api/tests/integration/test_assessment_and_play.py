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

import datetime as dt
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


# --- the mastery loop -------------------------------------------------------
#
# Until this section existed, `skill_states` and `mastery_events` had exactly
# one writer in the whole repository: the `sanad rag demo` seeder. Attempts
# accumulated, the dashboard counted sessions and minutes, and `p_known` never
# moved -- so no skill left `not_started` and nothing could ever reach
# `mastered`. Every piece was built and tested; nothing called them.
#
# These tests are deliberately end-to-end over HTTP and real Postgres. A unit
# test with a fake repository cannot notice that a service is never constructed.


async def _play(
    client: AsyncClient,
    headers: dict[str, str],
    child_id: str,
    *,
    outcomes: list[bool],
    tag: str,
    start_day: int = 0,
) -> str:
    """Run one session whose attempts are spread over one day each.

    `client_ts` is client-supplied, which is what lets a test span the calendar
    the mastery rule cares about -- two distinct days, and a correct answer at
    least three days after the first one -- without waiting three days.
    """
    created = (
        await client.post("/play/sessions", json={"child_id": child_id}, headers=headers)
    ).json()
    session_id = created["session_id"]
    activity = created["activities"][0]

    base = dt.datetime(2026, 3, 1, 9, 0, tzinfo=dt.UTC)
    await client.post(
        f"/play/sessions/{session_id}/attempts/batch",
        json={
            "attempts": [
                {
                    "activity_code": activity["activity_code"],
                    "skill_code": activity["skill_code"],
                    "result": "correct" if correct else "incorrect",
                    "prompt_level": "independent",
                    "choice_count": 2,
                    "latency_ms": 2000,
                    "client_ts": (base + dt.timedelta(days=start_day + n)).isoformat(),
                    "idempotency_key": f"{tag}-{n:04d}",
                }
                for n, correct in enumerate(outcomes)
            ]
        },
        headers=headers,
    )
    ended = await client.post(
        f"/play/sessions/{session_id}/end",
        json={"reason": "completed", "minutes": 5},
        headers=headers,
    )
    assert ended.status_code == 200, ended.text
    return str(session_id)


async def _state_of(session, child_id: str, code: str):  # type: ignore[no-untyped-def]
    return (
        await session.execute(
            text("""
                SELECT st.state::text AS state, st.p_known, st.total_attempts,
                       st.total_correct, st.distinct_days, st.due_at
                FROM skill_states st JOIN skills s ON s.id = st.skill_id
                WHERE st.child_id = CAST(:child AS uuid) AND s.code = :code
                  -- Explicit since 0012: one skill can now hold a receptive and
                  -- an expressive row, and an unfiltered read would pick either.
                  AND st.modality = 'receptive'
            """),
            {"child": child_id, "code": code},
        )
    ).first()


async def test_finishing_a_session_writes_a_skill_state(client: AsyncClient, session) -> None:  # type: ignore[no-untyped-def]
    """The connection that was missing, stated as its acceptance criterion."""
    _, child_id, headers = await _seed_family(session)
    await _seed_skills(session)

    before = await _state_of(session, child_id, "color_red")
    assert before is None, "no state before the child has played"

    await _play(client, headers, child_id, outcomes=[True, True, True], tag="first")

    after = await _state_of(session, child_id, "color_red")
    assert after is not None, "ending a session must write a skill state"
    assert after.total_attempts == 3
    assert after.total_correct == 3
    # 0.15 is the prior. Anything else means the attempts were actually folded
    # in rather than a default row being inserted.
    assert after.p_known > 0.15
    assert after.state == "introduced"
    assert after.due_at is not None, "a practised skill must be scheduled for review"


async def test_the_transition_is_recorded_as_a_mastery_event(client: AsyncClient, session) -> None:  # type: ignore[no-untyped-def]
    """`ai_cannot_grant` lives on `mastery_events`, so a silent transition
    would route around the one constraint P07 asked the database to enforce."""
    _, child_id, headers = await _seed_family(session)
    await _seed_skills(session)
    await _play(client, headers, child_id, outcomes=[True, True], tag="evt")

    rows = list(
        await session.execute(
            text("""
                SELECT from_state::text AS moved_from, to_state::text AS moved_to,
                       rule_satisfied, session_id
                FROM mastery_events WHERE child_id = CAST(:child AS uuid)
            """),
            {"child": child_id},
        )
    )
    assert [(r.moved_from, r.moved_to) for r in rows] == [("not_started", "introduced")]
    assert rows[0].rule_satisfied is False
    assert rows[0].session_id is not None, "an event must name the session that caused it"


async def test_replaying_the_same_attempts_does_not_move_p_known(
    client: AsyncClient, session
) -> None:  # type: ignore[no-untyped-def]
    """The fold restarts from the prior every time, so it is idempotent.

    This is why the recompute reads the whole history instead of incrementing.
    An incremental update would make a number in a clinical record depend on how
    many times a retry happened to fire.
    """
    _, child_id, headers = await _seed_family(session)
    await _seed_skills(session)
    session_id = await _play(client, headers, child_id, outcomes=[True, False, True], tag="idem")

    first = await _state_of(session, child_id, "color_red")

    replayed = await client.post(
        f"/play/sessions/{session_id}/end",
        json={"reason": "completed", "minutes": 5},
        headers=headers,
    )
    assert replayed.status_code == 200

    second = await _state_of(session, child_id, "color_red")
    assert second.p_known == first.p_known
    assert second.total_attempts == first.total_attempts


async def test_a_child_who_genuinely_learns_reaches_mastered(client: AsyncClient, session) -> None:  # type: ignore[no-untyped-def]
    """The positive control, and it is the point.

    Without it the random-tapper test below is satisfied by a rule that never
    grants mastery to anyone, which would pass every safety assertion and ship a
    product where no child ever succeeds.

    **Forty attempts, and the number is forced.** A first draft used twenty and
    failed: at two choices the accuracy guard demands

        accuracy >= chance + sqrt( ln(looks / 1e-5) / (2 * window) )

    and at n = 20 that is 0.5 + 0.602 = 1.102 -- above 1.0, so a PERFECT child
    cannot satisfy it. The break-even is around thirty attempts on one skill,
    and the margin only relaxes as the window fills to `ACCURACY_WINDOW` = 40.

    That is not a quirk of this test. REVIEW-QUEUE #5 already measured the same
    threshold in simulation -- "2 choices, 100% accurate: 30 attempts" -- and
    this is that number arrived at independently, over HTTP and Postgres. It is
    a property of the addition `mastery.py` documents as unreviewed, and nobody
    clinical has agreed to it. → REVIEW-QUEUE #5
    """
    _, child_id, headers = await _seed_family(session)
    await _seed_skills(session)

    # Independent correct answers, one per day: distinct days, a delayed pass
    # well past the three-day requirement, and accuracy 1.0 against chance 0.5.
    await _play(client, headers, child_id, outcomes=[True] * 40, tag="learner")

    state = await _state_of(session, child_id, "color_red")
    assert state.state == "mastered"
    assert state.distinct_days == 40


async def test_a_random_tapper_never_reaches_mastered_through_the_real_path(
    client: AsyncClient, session
) -> None:  # type: ignore[no-untyped-def]
    """P07's safety net, exercised through HTTP and Postgres rather than in pure code.

    Alternating rather than randomised, so the test is deterministic: accuracy
    lands on exactly 0.5, which is exactly the chance level at two choices, and
    the anytime-valid margin in `mastery.accuracy_margin` is what has to reject
    it. `p_known` still saturates -- that is the structural property that made
    the addition necessary -- so this asserts on the STATE, not the estimate.
    """
    _, child_id, headers = await _seed_family(session)
    await _seed_skills(session)

    tapping = [n % 2 == 0 for n in range(40)]
    await _play(client, headers, child_id, outcomes=tapping, tag="tapper")

    state = await _state_of(session, child_id, "color_red")
    assert state.state != "mastered"
    assert state.state != "retained"
    # The estimate saturating while the state does not move is the whole reason
    # the accuracy guard exists. Asserting it here stops anyone "fixing" the
    # test by making p_known behave instead.
    assert state.p_known > 0.9


async def test_a_modality_this_session_never_touched_does_not_advance(
    client: AsyncClient, session
) -> None:  # type: ignore[no-untyped-def]
    """A state with no attempts behind it must not climb the ladder.

    `next_state` advances one rung whenever the mastery rule is unmet -- and for
    a skill with an empty history it is unmet only because there is no evidence.
    A receptive session must therefore not walk an EXPRESSIVE state forward on
    the same skill. Found by reading the code rather than by a failure, which is
    why it is pinned here.
    """
    _, child_id, headers = await _seed_family(session)
    await _seed_skills(session)

    skill_id = (
        await session.execute(text("SELECT id FROM skills WHERE code = 'color_red'"))
    ).scalar_one()
    await session.execute(
        text("""
            INSERT INTO skill_states (child_id, skill_id, modality, state, p_known)
            VALUES (CAST(:child AS uuid), :skill, 'expressive', 'introduced', 0.4)
        """),
        {"child": child_id, "skill": skill_id},
    )

    await _play(client, headers, child_id, outcomes=[True, True], tag="modality")

    expressive = (
        await session.execute(
            text("""
                SELECT state::text AS state, p_known FROM skill_states
                WHERE child_id = CAST(:child AS uuid) AND skill_id = :skill
                  AND modality = 'expressive'
            """),
            {"child": child_id, "skill": skill_id},
        )
    ).one()
    assert expressive.state == "introduced", "an untouched modality must not advance"
    assert expressive.p_known == 0.4

    receptive = await _state_of(session, child_id, "color_red")
    assert receptive.state == "introduced", "the modality that WAS played still advances"


async def test_the_database_refuses_a_mastered_transition_the_rule_did_not_justify(
    client: AsyncClient, session
) -> None:  # type: ignore[no-untyped-def]
    """The `ai_cannot_grant` CHECK, against a real database at last.

    P07 has wanted this since it was written and BLOCKED.md has carried it as
    outstanding ever since: the application rule was tested, the database
    backstop never was. This writes the row an AI verdict would have to write to
    promote a child on its own authority, and asserts Postgres rejects it.
    """
    from sqlalchemy.exc import IntegrityError

    _, child_id, headers = await _seed_family(session)
    await _seed_skills(session)
    await _play(client, headers, child_id, outcomes=[True], tag="check")

    skill_id = (
        await session.execute(text("SELECT id FROM skills WHERE code = 'color_red'"))
    ).scalar_one()

    with pytest.raises(IntegrityError) as raised:
        await session.execute(
            text("""
                INSERT INTO mastery_events (
                    child_id, skill_id, from_state, to_state,
                    p_known_at_event, rule_satisfied, ai_verdict
                ) VALUES (
                    CAST(:child AS uuid), :skill, 'practising', 'mastered',
                    0.9900, false, 'confirm'
                )
            """),
            {"child": child_id, "skill": skill_id},
        )
    # The asyncpg dialect re-wraps the driver's CheckViolationError in its own
    # IntegrityError, so the constraint's NAME in the message is the assertion
    # that actually pins this to `ai_cannot_grant` rather than to any check.
    assert "ai_cannot_grant" in str(raised.value.orig)
    assert "CheckViolationError" in str(raised.value.orig)
    await session.rollback()
