"""The whole teaching loop, against real Postgres, over real HTTP.

Everything here needs a database, and needs one for the same reason the
`test_assessment_and_play.py` cases did: the properties being asserted are
about SQL — a unique index that makes a double tap one star, a CHECK constraint
that refuses an AI-granted mastery, a fold that reads back what it wrote. A test
with a fake repository cannot notice a missing constraint.

The chain this file walks is the one the specification's acceptance section
lists, in order:

    create child -> caregiver assessment -> assessment persisted
      -> learner state created -> teaching decision -> guardrails
      -> personalised activity -> incorrect response -> NO success
      -> attempt persisted -> learner state updated -> adaptation
      -> next activity -> correct response -> drawing fail -> drawing pass
      -> speech -> rewards persisted -> session completed -> caregiver report
      -> AI inspector on real rows -> "log out, log in" -> everything still there

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
from app.modules.starting.domain import form
from app.modules.tutor.domain.drawing import resample

pytestmark = pytest.mark.integration

CANVAS = 400.0

INSERT_CAREGIVER = text("""
    INSERT INTO caregivers (id, phone_e164, display_name)
    VALUES (CAST(:id AS uuid), :phone, 'T')
""")

INSERT_CHILD = text("""
    INSERT INTO children (id, display_name, date_of_birth, comms_level, max_choices)
    VALUES (CAST(:id AS uuid), :name, DATE '2019-05-01', 'single_words', :max_choices)
""")

LINK = text("""
    INSERT INTO caregiver_child (caregiver_id, child_id, role)
    VALUES (CAST(:caregiver_id AS uuid), CAST(:child_id AS uuid), 'owner')
""")

GRANT_CONSENTS = text("""
    INSERT INTO consents (child_id, caregiver_id, consent_key, version, status)
    SELECT CAST(:child_id AS uuid), CAST(:caregiver_id AS uuid), cd.key, cd.version, 'granted'
    FROM consent_definitions cd
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
""")


@pytest.fixture
def settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
async def session(settings: Settings):  # type: ignore[no-untyped-def]
    """A session inside an outer transaction that is always rolled back.

    `join_transaction_mode="create_savepoint"` turns each route's commit into a
    savepoint release, so the teardown rollback still has everything to undo.
    See the long note on the same fixture in `test_assessment_and_play.py`.
    """
    engine = init_engine(settings)
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


def _app(settings: Settings, session: AsyncSession):  # type: ignore[no-untyped-def]
    app = create_app(settings)

    async def _session_override():  # type: ignore[no-untyped-def]
        yield session

    app.dependency_overrides[get_session] = _session_override
    return app


@pytest.fixture
async def client(settings: Settings, session):  # type: ignore[no-untyped-def]
    app = _app(settings, session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


async def _seed_curriculum(session) -> None:  # type: ignore[no-untyped-def]
    """Enough of the real curriculum for every activity type to be buildable.

    Real codes, because `seeds/tracing.py` keys its reference paths on them and
    `build.numeral_value` parses them. A synthetic `skill_1` would make the
    tracing and counting activities untestable here.
    """
    rows = [
        ("color_red", "colors", "أحمر", 0),
        ("color_blue", "colors", "أزرق", 1),
        ("color_yellow", "colors", "أصفر", 2),
        ("color_green", "colors", "أخضر", 3),
        ("hh_cup", "household", "كوباية", 10),
        ("hh_plate", "household", "طبق", 11),
        ("num_1", "numbers", "١", 20),
        ("num_2", "numbers", "٢", 21),
        ("num_5", "numbers", "٥", 22),
        ("letter_alef", "letters", "أ", 30),
        ("letter_baa", "letters", "ب", 31),
        ("letter_taa", "letters", "ت", 32),
        ("social_thanks", "social", "شكرا", 40),
        ("social_yes", "social", "أيوه", 41),
    ]
    for code, category, label, order in rows:
        await session.execute(
            INSERT_SKILL,
            {"code": code, "category": category, "label_ar": label, "intro_order": order},
        )


async def _family(session, *, max_choices: int = 2, name: str = "تجربة"):  # type: ignore[no-untyped-def]
    caregiver_id = str(uuid.uuid4())
    child_id = str(uuid.uuid4())
    suffix = caregiver_id.replace("-", "")[:9]
    await session.execute(INSERT_CAREGIVER, {"id": caregiver_id, "phone": f"+2011{suffix}"})
    await session.execute(INSERT_CHILD, {"id": child_id, "name": name, "max_choices": max_choices})
    await session.execute(LINK, {"caregiver_id": caregiver_id, "child_id": child_id})
    await session.execute(GRANT_CONSENTS, {"child_id": child_id, "caregiver_id": caregiver_id})
    token, _ = issue_access_token(caregiver_id=uuid.UUID(caregiver_id))
    return caregiver_id, child_id, {"Authorization": f"Bearer {token}"}


async def _complete_starting_assessment(
    client: AsyncClient, headers: dict[str, str], child_id: str, answer: str = "sometimes"
) -> dict[str, Any]:
    started = await client.post(
        "/starting-assessments", json={"child_id": child_id}, headers=headers
    )
    assert started.status_code == 201, started.text
    assessment_id = started.json()["assessment_id"]
    for question in form.QUESTIONS:
        value = "medium" if not question.uses_bands else answer
        answered = await client.post(
            f"/starting-assessments/{assessment_id}/answers",
            json={"question_id": question.id, "answer_id": value},
            headers=headers,
        )
        assert answered.status_code == 200, answered.text
    finalised = await client.post(
        f"/starting-assessments/{assessment_id}/finalise", headers=headers
    )
    assert finalised.status_code == 200, finalised.text
    return finalised.json()


async def _next(client: AsyncClient, headers: dict[str, str], session_id: str) -> dict[str, Any]:
    got = await client.post(f"/tutor/sessions/{session_id}/next", headers=headers)
    assert got.status_code == 200, got.text
    return got.json()


def _answer_body(activity: dict[str, Any], *, correct: bool = True) -> dict[str, Any]:
    """The response a child would produce for this activity."""
    presentation = activity["presentation"]
    kind = activity["activity_type"]
    if kind in ("select_picture", "listen_choose", "match_pair"):
        options = presentation["options"]
        target = next(
            option for option in options if option["skill_code"] == activity["skill_code"]
        )
        if correct:
            return {"kind": "choice", "option_id": target["option_id"]}
        other = next(option for option in options if option["option_id"] != target["option_id"])
        return {"kind": "choice", "option_id": other["option_id"]}
    if kind == "count_objects":
        value = presentation["object_count"]
        return {"kind": "count", "value": value if correct else value + 1}
    if kind == "sort_category":
        assignments = {
            option["option_id"]: (option["category"] if correct else "__nowhere__")
            for option in presentation["options"]
        }
        return {"kind": "sort", "assignments": assignments}
    if kind == "order_sequence":
        ids = [option["option_id"] for option in presentation["options"]]
        ordered = sorted(ids)
        return {"kind": "sequence", "order": ordered if correct else list(reversed(ordered))}
    if kind == "speak_word":
        return {
            "kind": "speech",
            "transcript": presentation["target_word_ar"] if correct else "حاجة تانية خالص",
            "confidence": 0.93,
        }
    if kind == "trace_letter":
        return _strokes_for(presentation["reference_path"], faithful=correct)
    return {"kind": "no_response"}


def _strokes_for(reference: list[Any], *, faithful: bool) -> dict[str, Any]:
    if not faithful:
        # A single dot: the specification's test table says it must FAIL.
        return {"kind": "strokes", "strokes": [[[200.0, 200.0]]], "width": CANVAS, "height": CANVAS}
    points = resample([[(float(x), float(y)) for x, y in stroke] for stroke in reference])
    return {
        "kind": "strokes",
        "strokes": [[[x * CANVAS, y * CANVAS] for x, y in points]],
        "width": CANVAS,
        "height": CANVAS,
    }


async def _respond(
    client: AsyncClient,
    headers: dict[str, str],
    session_id: str,
    activity: dict[str, Any],
    body: dict[str, Any],
    *,
    key: str | None = None,
    prompt_level: str = "independent",
) -> dict[str, Any]:
    answered = await client.post(
        f"/tutor/sessions/{session_id}/respond",
        json={
            "activity_id": activity["activity_id"],
            "response": body,
            "idempotency_key": key or f"k-{session_id}-{activity['ordinal']}",
            "latency_ms": 2400,
            "prompt_level": prompt_level,
        },
        headers=headers,
    )
    assert answered.status_code == 200, answered.text
    return answered.json()


# ===========================================================================
# The chain
# ===========================================================================


async def test_a_new_child_gets_an_assessment_a_learner_state_and_a_first_decision(
    client: AsyncClient, session
) -> None:  # type: ignore[no-untyped-def]
    """Create child -> assessment -> persisted -> learner state -> decision.

    The four arrows the specification puts before the first activity, each
    checked against the database rather than against the response body.
    """
    await _seed_curriculum(session)
    _caregiver, child_id, headers = await _family(session)

    result = await _complete_starting_assessment(client, headers, child_id)
    assert result["status"] == "completed"
    assert result["skills_seeded"] > 0
    assert set(result["area_levels"]) >= {"colors", "numbers", "letters"}

    stored = (
        await session.execute(
            text(
                "SELECT count(*) AS n, count(p_prior) AS priors FROM skill_states "
                "WHERE child_id = CAST(:c AS uuid)"
            ),
            {"c": child_id},
        )
    ).one()
    assert stored.n == result["skills_seeded"]
    assert stored.priors == stored.n, "every seeded state carries its own prior"

    profile = (
        await session.execute(
            text("SELECT * FROM learner_profiles WHERE child_id = CAST(:c AS uuid)"),
            {"c": child_id},
        )
    ).one()
    assert profile.effective_support in ("low", "medium", "high")

    started = await client.post("/tutor/sessions", json={"child_id": child_id}, headers=headers)
    assert started.status_code == 201, started.text
    session_id = started.json()["session_id"]

    activity = await _next(client, headers, session_id)
    assert not activity["session_finished"]
    assert activity["skill_code"]
    assert activity["reason_codes"], "a decision with no reason codes explains nothing"

    decision = (
        await session.execute(
            text("SELECT count(*) AS n FROM ai_decisions WHERE session_id = CAST(:s AS uuid)"),
            {"s": session_id},
        )
    ).one()
    assert decision.n == 1, "the teaching decision is a persisted row, not a log line"


async def test_the_caregiver_assessment_can_never_produce_mastery(
    client: AsyncClient, session
) -> None:  # type: ignore[no-untyped-def]
    """A parent's recollection is initial evidence. It is not a mastery badge.

    Answered at the top band on every question, which is the strongest claim the
    form can carry.
    """
    await _seed_curriculum(session)
    _caregiver, child_id, headers = await _family(session)
    await _complete_starting_assessment(client, headers, child_id, answer="usually")

    states = list(
        await session.execute(
            text(
                "SELECT state::text AS state, p_known FROM skill_states "
                "WHERE child_id = CAST(:c AS uuid)"
            ),
            {"c": child_id},
        )
    )
    assert states
    assert all(row.state in ("introduced", "practising") for row in states)
    assert all(float(row.p_known) < 0.90 for row in states)


async def test_an_incorrect_answer_is_incorrect_and_earns_nothing(
    client: AsyncClient, session
) -> None:  # type: ignore[no-untyped-def]
    """The no-false-success rule, at the one place it could be broken."""
    await _seed_curriculum(session)
    _caregiver, child_id, headers = await _family(session)
    await _complete_starting_assessment(client, headers, child_id)
    started = await client.post("/tutor/sessions", json={"child_id": child_id}, headers=headers)
    session_id = started.json()["session_id"]

    activity = await _next(client, headers, session_id)
    result = await _respond(
        client, headers, session_id, activity, _answer_body(activity, correct=False)
    )

    assert result["correct"] is False
    assert result["outcome"] == "incorrect"
    assert result["reward_delta"] == 0
    assert result["stars_total"] == 0
    assert result["next_action"] == "retry"

    stored = (
        await session.execute(
            text("SELECT result::text AS result FROM attempts WHERE session_id = CAST(:s AS uuid)"),
            {"s": session_id},
        )
    ).one()
    assert stored.result == "incorrect"

    stars = (
        await session.execute(
            text(
                "SELECT COALESCE(sum(stars), 0) AS stars FROM reward_events "
                "WHERE child_id = CAST(:c AS uuid)"
            ),
            {"c": child_id},
        )
    ).one()
    assert stars.stars == 0


async def test_the_client_is_never_sent_the_answer(client: AsyncClient, session) -> None:  # type: ignore[no-untyped-def]
    """The wire-format half of "the frontend does not decide correctness".

    The answer key is in a column, and `ActivityOut` has no field for it — so a
    client cannot mark itself correct, because it does not have the information
    to.
    """
    await _seed_curriculum(session)
    _caregiver, child_id, headers = await _family(session)
    await _complete_starting_assessment(client, headers, child_id)
    started = await client.post("/tutor/sessions", json={"child_id": child_id}, headers=headers)
    session_id = started.json()["session_id"]

    got = await client.post(f"/tutor/sessions/{session_id}/next", headers=headers)
    body = got.text
    assert "answer_key" not in body
    assert '"correct"' not in body
    assert "pass_threshold" not in body

    activity = got.json()
    stored = (
        await session.execute(
            text("SELECT answer_key FROM tutor_activities WHERE id = CAST(:a AS uuid)"),
            {"a": activity["activity_id"]},
        )
    ).one()
    assert stored.answer_key, "the answer exists — on the server"


async def test_a_wrong_answer_changes_what_the_child_is_asked_next(
    client: AsyncClient, session
) -> None:  # type: ignore[no-untyped-def]
    """Adaptation, inside one session, from evidence recorded seconds earlier.

    Two wrong answers on the same skill and the decision has to move: the same
    skill again, at the lowest difficulty, with the support raised and a
    demonstration in front of it.
    """
    await _seed_curriculum(session)
    _caregiver, child_id, headers = await _family(session)
    await _complete_starting_assessment(client, headers, child_id, answer="usually")
    started = await client.post("/tutor/sessions", json={"child_id": child_id}, headers=headers)
    session_id = started.json()["session_id"]

    first = await _next(client, headers, session_id)
    await _respond(client, headers, session_id, first, _answer_body(first, correct=False))
    second = await _next(client, headers, session_id)
    await _respond(client, headers, session_id, second, _answer_body(second, correct=False))
    third = await _next(client, headers, session_id)

    assert third["skill_code"] == first["skill_code"], "the failed skill is retried"
    assert third["support_level"] == "high"
    assert third["difficulty"] <= first["difficulty"]
    assert third["presentation"]["demonstration_ar"]
    assert "RECENT_ERRORS" in third["reason_codes"]


async def test_every_answer_moves_the_estimate_and_the_move_is_persisted(
    client: AsyncClient, session
) -> None:  # type: ignore[no-untyped-def]
    """`p_known` is a column, and the number the client is shown is that column.

    Read back from `skill_states` rather than trusted from the response: the
    whole point of the fold running per response is that the estimate on screen
    is the estimate on file.
    """
    await _seed_curriculum(session)
    _caregiver, child_id, headers = await _family(session)
    await _complete_starting_assessment(client, headers, child_id)
    started = await client.post("/tutor/sessions", json={"child_id": child_id}, headers=headers)
    session_id = started.json()["session_id"]

    reported: list[tuple[str, float]] = []
    for _ in range(4):
        activity = await _next(client, headers, session_id)
        if activity["session_finished"]:
            break
        result = await _respond(
            client, headers, session_id, activity, _answer_body(activity, correct=True)
        )
        assert result["mastery_after"] is not None
        assert result["mastery_state"]
        reported.append((activity["skill_code"], result["mastery_after"]))

    assert reported
    for skill_code, value in reported:
        stored = (
            await session.execute(
                text(
                    "SELECT p_known, total_attempts FROM skill_states st "
                    "JOIN skills s ON s.id = st.skill_id "
                    "WHERE st.child_id = CAST(:c AS uuid) AND s.code = :code"
                ),
                {"c": child_id, "code": skill_code},
            )
        ).one()
        assert float(stored.p_known) == pytest.approx(value, abs=1e-4)
        assert stored.total_attempts > 0

    # A skill answered twice moved twice, in the right direction.
    repeated = [code for code, _ in reported]
    if len(set(repeated)) < len(repeated):
        first_code = next(code for code in repeated if repeated.count(code) > 1)
        values = [value for code, value in reported if code == first_code]
        assert values == sorted(values), "correct answers must not lower the estimate"


async def test_a_state_change_writes_a_mastery_event(client: AsyncClient, session) -> None:  # type: ignore[no-untyped-def]
    """`mastery_events` records TRANSITIONS, not attempts.

    A child with no starting assessment begins every skill at `not_started`, so
    their first answer moves the ladder and the move is a row. A child whose
    caregiver put them at `practising` does NOT get an event for staying there,
    which is why this test does not run the assessment first.
    """
    await _seed_curriculum(session)
    _caregiver, child_id, headers = await _family(session)
    started = await client.post("/tutor/sessions", json={"child_id": child_id}, headers=headers)
    session_id = started.json()["session_id"]

    activity = await _next(client, headers, session_id)
    await _respond(client, headers, session_id, activity, _answer_body(activity))

    events = list(
        await session.execute(
            text(
                "SELECT from_state::text AS from_state, to_state::text AS to_state, "
                "rule_satisfied, ai_verdict FROM mastery_events "
                "WHERE child_id = CAST(:c AS uuid)"
            ),
            {"c": child_id},
        )
    )
    assert events
    assert events[0].from_state == "not_started"
    assert events[0].to_state == "introduced"
    # The deterministic verdict, never an AI one. `ai_cannot_grant` checks this
    # column, so an AI verdict written here would disarm the constraint while
    # leaving it looking armed.
    assert events[0].rule_satisfied is False
    assert events[0].ai_verdict is None


# ===========================================================================
# Idempotency
# ===========================================================================


async def test_the_same_response_twice_is_one_attempt_and_one_star(
    client: AsyncClient, session
) -> None:  # type: ignore[no-untyped-def]
    """Rapid tapping, a retry after a timeout, and an outbox draining twice all
    look like this to the server, and all have to cost nothing."""
    await _seed_curriculum(session)
    _caregiver, child_id, headers = await _family(session)
    await _complete_starting_assessment(client, headers, child_id)
    started = await client.post("/tutor/sessions", json={"child_id": child_id}, headers=headers)
    session_id = started.json()["session_id"]

    activity = await _next(client, headers, session_id)
    body = _answer_body(activity, correct=True)
    first = await _respond(client, headers, session_id, activity, body, key="same-key-1")
    assert first["duplicate"] is False
    assert first["reward_delta"] > 0

    for _ in range(5):
        again = await _respond(client, headers, session_id, activity, body, key="same-key-1")
        assert again["duplicate"] is True
        assert again["reward_delta"] == 0
        assert again["stars_total"] == first["stars_total"]

    counts = (
        await session.execute(
            text(
                "SELECT (SELECT count(*) FROM attempts WHERE session_id = CAST(:s AS uuid)) "
                "AS attempts, "
                "(SELECT count(*) FROM reward_events WHERE session_id = CAST(:s AS uuid)) "
                "AS rewards"
            ),
            {"s": session_id},
        )
    ).one()
    assert counts.attempts == 1
    assert counts.rewards == 1


async def test_asking_for_the_next_activity_twice_returns_the_same_activity(
    client: AsyncClient, session
) -> None:  # type: ignore[no-untyped-def]
    """A reload mid-session must not move the cards under a child's finger."""
    await _seed_curriculum(session)
    _caregiver, child_id, headers = await _family(session)
    await _complete_starting_assessment(client, headers, child_id)
    started = await client.post("/tutor/sessions", json={"child_id": child_id}, headers=headers)
    session_id = started.json()["session_id"]

    first = await _next(client, headers, session_id)
    second = await _next(client, headers, session_id)
    assert first["activity_id"] == second["activity_id"]
    assert first["presentation"]["options"] == second["presentation"]["options"]

    rows = (
        await session.execute(
            text("SELECT count(*) AS n FROM tutor_activities WHERE session_id = CAST(:s AS uuid)"),
            {"s": session_id},
        )
    ).one()
    assert rows.n == 1


async def test_ending_a_session_twice_does_not_double_the_completion_bonus(
    client: AsyncClient, session
) -> None:  # type: ignore[no-untyped-def]
    await _seed_curriculum(session)
    _caregiver, child_id, headers = await _family(session)
    await _complete_starting_assessment(client, headers, child_id)
    started = await client.post("/tutor/sessions", json={"child_id": child_id}, headers=headers)
    session_id = started.json()["session_id"]
    activity = await _next(client, headers, session_id)
    await _respond(client, headers, session_id, activity, _answer_body(activity))

    first = await client.post(
        f"/tutor/sessions/{session_id}/end",
        json={"reason": "completed", "minutes": 4},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    second = await client.post(
        f"/tutor/sessions/{session_id}/end",
        json={"reason": "completed", "minutes": 4},
        headers=headers,
    )
    assert second.status_code == 200, second.text
    assert second.json()["stars_total"] == first.json()["stars_total"]


# ===========================================================================
# Drawing and speech, on the real path
# ===========================================================================


async def _activity_of_type(
    client: AsyncClient,
    headers: dict[str, str],
    session_id: str,
    session,  # type: ignore[no-untyped-def]
    wanted: str,
    child_id: str,
) -> dict[str, Any]:
    """Force one activity of a given type, by writing the row the way the
    service writes it.

    The alternative is answering activities until the brain happens to choose
    the type — which is a slow test whose failure mode is a timeout rather than
    a message. What is under test here is the RESPONSE path, and it reads the
    stored row.
    """
    from app.modules.tutor.domain.build import SkillRow, build
    from app.modules.tutor.domain.contract import MODALITY_OF, ActivityType
    from app.modules.tutor.repository import TutorRepository

    activity_type = ActivityType(wanted)
    code = "letter_baa" if activity_type is ActivityType.TRACE_LETTER else "color_red"
    row = (
        await session.execute(
            text(
                "SELECT id, code, category::text AS category, label_ar, label_egy, "
                "alt_text_ar, intro_order FROM skills WHERE code = :code"
            ),
            {"code": code},
        )
    ).one()
    target = SkillRow(
        skill_id=str(row.id),
        code=str(row.code),
        category=str(row.category),
        label_ar=str(row.label_ar),
        label_egy=str(row.label_egy),
        alt_text_ar=str(row.alt_text_ar),
        intro_order=int(row.intro_order),
    )
    built = build(
        activity_type=activity_type,
        target=target,
        pool=[],
        difficulty=1,
        modality=MODALITY_OF[activity_type],
        strategy="independent_practice",
        support_level="low",
        prompt_level="independent",
        demonstrate_first=False,
        max_choices=2,
        seed=3,
    )
    ordinal = await TutorRepository(session).activity_count(uuid.UUID(session_id)) + 1
    inserted = await TutorRepository(session).insert_activity(
        {
            "session_id": uuid.UUID(session_id),
            "child_id": uuid.UUID(child_id),
            "decision_id": None,
            "ordinal": ordinal,
            "activity_type": str(activity_type),
            "skill_id": row.id,
            "skill_code": built.skill_code,
            "difficulty": built.difficulty,
            "modality": built.modality,
            "strategy": built.strategy,
            "support_level": built.support_level,
            "prompt_level": built.prompt_level,
            "choice_count": built.choice_count,
            "presentation": built.presentation.as_json(),
            "answer_key": built.answer_key.as_json(),
        }
    )
    return {
        "activity_id": str(inserted.id),
        "ordinal": int(inserted.ordinal),
        "activity_type": str(activity_type),
        "skill_code": built.skill_code,
        "presentation": built.presentation.as_json(),
    }


async def test_a_poor_drawing_fails_and_a_faithful_one_passes(client: AsyncClient, session) -> None:  # type: ignore[no-untyped-def]
    """The specification's demo beat, on the real path with the real metrics."""
    await _seed_curriculum(session)
    _caregiver, child_id, headers = await _family(session)
    await _complete_starting_assessment(client, headers, child_id)
    started = await client.post("/tutor/sessions", json={"child_id": child_id}, headers=headers)
    session_id = started.json()["session_id"]

    poor_activity = await _activity_of_type(
        client, headers, session_id, session, "trace_letter", child_id
    )
    poor = await _respond(
        client,
        headers,
        session_id,
        poor_activity,
        _strokes_for(poor_activity["presentation"]["reference_path"], faithful=False),
        key=f"draw-bad-{session_id}",
    )
    assert poor["correct"] is False
    assert poor["score"] is not None and poor["threshold"] is not None
    assert poor["score"] < poor["threshold"]
    assert poor["reward_delta"] == 0

    good_activity = await _activity_of_type(
        client, headers, session_id, session, "trace_letter", child_id
    )
    good = await _respond(
        client,
        headers,
        session_id,
        good_activity,
        _strokes_for(good_activity["presentation"]["reference_path"], faithful=True),
        key=f"draw-good-{session_id}",
    )
    assert good["correct"] is True
    assert good["score"] >= good["threshold"]
    assert good["reward_delta"] > 0

    outcomes = list(
        await session.execute(
            text(
                "SELECT correctness, similarity, threshold, metrics FROM activity_outcomes "
                "WHERE child_id = CAST(:c AS uuid) ORDER BY created_at, id"
            ),
            {"c": child_id},
        )
    )
    assert [row.correctness for row in outcomes] == [False, True]
    assert all(row.metrics and row.threshold is not None for row in outcomes)
    assert all("coverage" in dict(row.metrics) for row in outcomes)


async def test_a_speech_attempt_the_recogniser_could_not_hear_is_not_a_wrong_answer(
    client: AsyncClient, session
) -> None:  # type: ignore[no-untyped-def]
    """Low confidence is uncertainty. It must not go on file as `incorrect`."""
    await _seed_curriculum(session)
    _caregiver, child_id, headers = await _family(session)
    await _complete_starting_assessment(client, headers, child_id)
    started = await client.post("/tutor/sessions", json={"child_id": child_id}, headers=headers)
    session_id = started.json()["session_id"]

    activity = await _activity_of_type(client, headers, session_id, session, "speak_word", child_id)
    unclear = await _respond(
        client,
        headers,
        session_id,
        activity,
        {"kind": "speech", "transcript": "", "confidence": 0.0, "recogniser_available": False},
        key=f"speech-unclear-{session_id}",
    )
    assert unclear["outcome"] == "uncertain"
    assert unclear["support_action"] == "caregiver_confirm"
    assert unclear["reward_delta"] == 0

    stored = (
        await session.execute(
            text("SELECT result::text AS result FROM attempts WHERE session_id = CAST(:s AS uuid)"),
            {"s": session_id},
        )
    ).one()
    assert stored.result == "no_response", "never `incorrect`"


async def test_a_caregiver_confirmation_carries_the_attempt(client: AsyncClient, session) -> None:  # type: ignore[no-untyped-def]
    await _seed_curriculum(session)
    _caregiver, child_id, headers = await _family(session)
    await _complete_starting_assessment(client, headers, child_id)
    started = await client.post("/tutor/sessions", json={"child_id": child_id}, headers=headers)
    session_id = started.json()["session_id"]

    activity = await _activity_of_type(client, headers, session_id, session, "speak_word", child_id)
    confirmed = await _respond(
        client,
        headers,
        session_id,
        activity,
        {"kind": "speech", "transcript": "", "confidence": 0.0, "caregiver_confirmed": True},
        key=f"speech-confirmed-{session_id}",
    )
    assert confirmed["correct"] is True
    assert confirmed["reward_delta"] > 0

    stored = (
        await session.execute(
            text("SELECT result::text AS result FROM attempts WHERE session_id = CAST(:s AS uuid)"),
            {"s": session_id},
        )
    ).one()
    assert stored.result == "caregiver_confirmed"


# ===========================================================================
# Session completion, report and inspector
# ===========================================================================


async def test_a_finished_session_has_facts_a_report_and_an_inspector(
    client: AsyncClient, session
) -> None:  # type: ignore[no-untyped-def]
    await _seed_curriculum(session)
    _caregiver, child_id, headers = await _family(session)
    await _complete_starting_assessment(client, headers, child_id)
    started = await client.post("/tutor/sessions", json={"child_id": child_id}, headers=headers)
    session_id = started.json()["session_id"]

    for index in range(4):
        activity = await _next(client, headers, session_id)
        if activity["session_finished"]:
            break
        await _respond(
            client,
            headers,
            session_id,
            activity,
            _answer_body(activity, correct=index % 2 == 0),
        )

    ended = await client.post(
        f"/tutor/sessions/{session_id}/end",
        json={"reason": "completed", "minutes": 6},
        headers=headers,
    )
    assert ended.status_code == 200, ended.text
    result = ended.json()
    assert result["activities_completed"] == 4
    assert result["correct"] + result["incorrect"] + result["no_response"] == 4
    assert result["narrative_ar"]
    assert result["narrative_source"] == "template"
    assert result["skills_practised_ar"]

    report = await client.get(f"/tutor/sessions/{session_id}/report", headers=headers)
    assert report.status_code == 200, report.text
    facts = report.json()["facts"]
    assert facts["activities_completed"] == result["activities_completed"]
    assert facts["correct"] == result["correct"]

    inspector = await client.get(f"/tutor/sessions/{session_id}/inspector", headers=headers)
    assert inspector.status_code == 200, inspector.text
    panel = inspector.json()
    assert len(panel["decisions"]) == 4
    assert len(panel["attempts"]) == 4
    for step in panel["decisions"]:
        assert step["reason_codes"], "a decision the panel cannot explain"
        assert step["skill"]
        assert step["p_known_at_decision"] is not None
        assert step["model_name"]
    # The panel is not the runtime's opinion; every field it shows is a column.
    stored = list(
        await session.execute(
            text(
                "SELECT final_decision, reason_codes FROM ai_decisions "
                "WHERE session_id = CAST(:s AS uuid) ORDER BY created_at, id"
            ),
            {"s": session_id},
        )
    )
    assert [list(row.reason_codes) for row in stored] == [
        step["reason_codes"] for step in panel["decisions"]
    ]


async def test_the_inspector_reports_the_deterministic_source_with_no_provider(
    client: AsyncClient, session
) -> None:  # type: ignore[no-untyped-def]
    """AI OFF is the default configuration, and it says so rather than
    presenting a deterministic rule as a model decision."""
    await _seed_curriculum(session)
    _caregiver, child_id, headers = await _family(session)
    await _complete_starting_assessment(client, headers, child_id)
    started = await client.post("/tutor/sessions", json={"child_id": child_id}, headers=headers)
    session_id = started.json()["session_id"]
    activity = await _next(client, headers, session_id)
    assert activity["decision_source"] == "deterministic_fallback"

    inspector = await client.get(f"/tutor/sessions/{session_id}/inspector", headers=headers)
    panel = inspector.json()
    assert panel["plan_source"] == "deterministic_fallback"
    assert panel["decisions"][0]["used_ai"] is False


# ===========================================================================
# Persistence and isolation
# ===========================================================================


async def test_rewards_and_learner_state_survive_a_restart(
    settings: Settings, client: AsyncClient, session
) -> None:  # type: ignore[no-untyped-def]
    """ "Log out, log in" as the server experiences it: a brand-new app
    instance, a brand-new token, the same database."""
    await _seed_curriculum(session)
    caregiver_id, child_id, headers = await _family(session)
    await _complete_starting_assessment(client, headers, child_id)
    started = await client.post("/tutor/sessions", json={"child_id": child_id}, headers=headers)
    session_id = started.json()["session_id"]
    for _ in range(3):
        activity = await _next(client, headers, session_id)
        if activity["session_finished"]:
            break
        await _respond(client, headers, session_id, activity, _answer_body(activity))
    await client.post(
        f"/tutor/sessions/{session_id}/end",
        json={"reason": "completed", "minutes": 5},
        headers=headers,
    )
    before = (await client.get(f"/children/{child_id}/rewards", headers=headers)).json()
    assert before["stars"] > 0

    # A second application, a second token. Same rows.
    restarted = _app(settings, session)
    token, _ = issue_access_token(caregiver_id=uuid.UUID(caregiver_id))
    fresh_headers = {"Authorization": f"Bearer {token}"}
    async with AsyncClient(
        transport=ASGITransport(app=restarted), base_url="http://test"
    ) as second:
        after = (await second.get(f"/children/{child_id}/rewards", headers=fresh_headers)).json()
        assert after["stars"] == before["stars"]
        assert after["achievements"] == before["achievements"]

        report = await second.get(f"/tutor/sessions/{session_id}/report", headers=fresh_headers)
        assert report.status_code == 200
        assert report.json()["facts"]["activities_completed"] > 0
    restarted.dependency_overrides.clear()


async def test_a_caregiver_cannot_reach_another_familys_child(client: AsyncClient, session) -> None:  # type: ignore[no-untyped-def]
    """Every tutor route, walked with the wrong token.

    The paths carry `{session_id}` rather than `{child_id}`, so
    `tools/guards/route_authorisation.py` cannot see them and the check lives in
    the service. This is what proves the check is there.
    """
    await _seed_curriculum(session)
    _one, child_a, headers_a = await _family(session, name="أ")
    _two, _child_b, headers_b = await _family(session, name="ب")

    await _complete_starting_assessment(client, headers_a, child_a)
    started = await client.post("/tutor/sessions", json={"child_id": child_a}, headers=headers_a)
    session_id = started.json()["session_id"]
    activity = await _next(client, headers_a, session_id)

    # Caregiver B, holding a valid token for their own child, against A's rows.
    refusals = [
        await client.post("/tutor/sessions", json={"child_id": child_a}, headers=headers_b),
        await client.post(f"/tutor/sessions/{session_id}/next", headers=headers_b),
        await client.post(
            f"/tutor/sessions/{session_id}/respond",
            json={
                "activity_id": activity["activity_id"],
                "response": {"kind": "choice", "option_id": "opt-0"},
                "idempotency_key": "intruder-key-1",
            },
            headers=headers_b,
        ),
        await client.post(
            f"/tutor/sessions/{session_id}/end", json={"minutes": 1}, headers=headers_b
        ),
        await client.get(f"/tutor/sessions/{session_id}/report", headers=headers_b),
        await client.get(f"/tutor/sessions/{session_id}/inspector", headers=headers_b),
        await client.get(f"/children/{child_a}/rewards", headers=headers_b),
        await client.get(f"/children/{child_a}/starting-assessment", headers=headers_b),
    ]
    assert all(response.status_code in (403, 404) for response in refusals), [
        (response.request.url.path, response.status_code) for response in refusals
    ]

    # And nothing was written into A's session by B's attempts.
    counts = (
        await session.execute(
            text("SELECT count(*) AS n FROM attempts WHERE session_id = CAST(:s AS uuid)"),
            {"s": session_id},
        )
    ).one()
    assert counts.n == 0


async def test_the_database_refuses_a_mastery_granted_by_an_ai_verdict(
    session,
) -> None:  # type: ignore[no-untyped-def]
    """The backstop, exercised rather than asserted about the DDL text.

    The exact row an AI verdict would need to promote a child on its own
    authority — `rule_satisfied = false`, `to_state = 'mastered'` — and Postgres
    rejecting it by name.
    """
    from asyncpg.exceptions import CheckViolationError
    from sqlalchemy.exc import IntegrityError

    await _seed_curriculum(session)
    caregiver_id, child_id, _headers = await _family(session)
    skill = (await session.execute(text("SELECT id FROM skills WHERE code = 'color_red'"))).one()
    play_session = (
        await session.execute(
            text(
                "INSERT INTO play_sessions (child_id, started_by) "
                "VALUES (CAST(:c AS uuid), CAST(:g AS uuid)) RETURNING id"
            ),
            {"c": child_id, "g": caregiver_id},
        )
    ).one()

    with pytest.raises(IntegrityError) as raised:
        await session.execute(
            text("""
                INSERT INTO mastery_events (
                    child_id, skill_id, modality, from_state, to_state,
                    p_known_at_event, rule_satisfied, ai_verdict, session_id
                ) VALUES (
                    CAST(:c AS uuid), :s, 'receptive', 'practising', 'mastered',
                    0.99, false, 'confirm', :p
                )
            """),
            {"c": child_id, "s": skill.id, "p": play_session.id},
        )
    assert isinstance(raised.value.orig.__cause__, CheckViolationError)
    assert "ai_cannot_grant" in str(raised.value)
    await session.rollback()


# ===========================================================================
# The three demo learners
# ===========================================================================


async def test_the_demo_children_get_measurably_different_sessions(
    client: AsyncClient, session
) -> None:  # type: ignore[no-untyped-def]
    """The demo's central claim, against the real seed and the real loop.

    Not "the sessions differ somewhere": every child's stored learner profile
    has to be distinct, and the tuple of teaching controls on their first
    activity has to take at least three different values across the four — so
    the differences are in their evidence rather than in a coincidence of
    ordering.
    """
    from seeds.curriculum import build_skills
    from seeds.demo import DEMO_CAREGIVER_ID, DEMO_CHILDREN
    from seeds.demo_loader import load

    # The full curriculum: the demo histories name skills across six categories.
    for skill in build_skills():
        await session.execute(
            INSERT_SKILL,
            {
                "code": skill.code,
                "category": skill.category,
                "label_ar": skill.label_ar,
                "intro_order": skill.intro_order,
            },
        )
    await load(session, today=dt.datetime.now(dt.UTC))

    token, _ = issue_access_token(caregiver_id=uuid.UUID(DEMO_CAREGIVER_ID))
    headers = {"Authorization": f"Bearer {token}"}

    signatures: dict[str, tuple[Any, ...]] = {}
    profiles: dict[str, tuple[Any, ...]] = {}
    for child in DEMO_CHILDREN:
        summary = await client.get(
            f"/children/{child.child_id}/starting-assessment", headers=headers
        )
        assert summary.status_code == 200, summary.text
        supports = summary.json()["supports"]
        profiles[child.display_name] = (
            supports["effective_support"],
            supports["effective_modality"],
            supports["comfortable_minutes"],
            tuple(sorted(summary.json()["area_levels"].items())),
        )

        started = await client.post(
            "/tutor/sessions", json={"child_id": child.child_id}, headers=headers
        )
        assert started.status_code == 201, started.text
        activity = await _next(client, headers, started.json()["session_id"])
        signatures[child.display_name] = (
            activity["activity_type"],
            activity["skill_code"],
            activity["difficulty"],
            activity["support_level"],
            activity["strategy"],
            activity["choice_count"],
        )

    assert len(set(profiles.values())) == len(DEMO_CHILDREN), profiles
    assert len(set(signatures.values())) >= 3, signatures

    # Each child has stars, and they are not the same number — the histories
    # earned them through the same rule the runtime uses.
    totals = {}
    for child in DEMO_CHILDREN:
        rewards = await client.get(f"/children/{child.child_id}/rewards", headers=headers)
        totals[child.display_name] = rewards.json()["stars"]
    assert all(value > 0 for value in totals.values()), totals
    assert len(set(totals.values())) > 1, totals

    # And at least one of them is offered a tracing activity first, because
    # their record says tracing is what they do best. That is the drawing beat
    # of the demo being reachable at all.
    assert any(signature[0] == "trace_letter" for signature in signatures.values()), signatures


async def test_seeding_the_demo_twice_changes_nothing(client: AsyncClient, session) -> None:  # type: ignore[no-untyped-def]
    """Idempotence, because `just seed-demo` is documented as safe to re-run."""
    from seeds.curriculum import build_skills
    from seeds.demo import DEMO_CHILDREN
    from seeds.demo_loader import load

    for skill in build_skills():
        await session.execute(
            INSERT_SKILL,
            {
                "code": skill.code,
                "category": skill.category,
                "label_ar": skill.label_ar,
                "intro_order": skill.intro_order,
            },
        )
    today = dt.datetime.now(dt.UTC)
    await load(session, today=today)

    def _counts():  # type: ignore[no-untyped-def]
        return session.execute(
            text("""
                SELECT
                  (SELECT count(*) FROM attempts)      AS attempts,
                  (SELECT count(*) FROM reward_events) AS rewards,
                  (SELECT count(*) FROM achievements)  AS achievements,
                  (SELECT COALESCE(sum(stars), 0) FROM reward_events) AS stars
            """)
        )

    before = (await _counts()).one()
    await load(session, today=today)
    after = (await _counts()).one()
    assert (before.attempts, before.rewards, before.achievements, before.stars) == (
        after.attempts,
        after.rewards,
        after.achievements,
        after.stars,
    )
    assert len(DEMO_CHILDREN) == 4
