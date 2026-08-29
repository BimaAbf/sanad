"""The RAG path against real Postgres and real pgvector.

Everything here is the half that unit tests structurally cannot reach: the SQL,
the `vector(256)` round trip, the HNSW-backed `<=>` ordering, and the
child-scoping of retrieval. `tests/unit/test_recommendation.py` covers the
in-memory retriever; if the two ever disagree, this file is right and that one
is measuring a fake.

The test worth reading first is `test_search_never_crosses_children`. It seeds
two children, gives one of them a document that is a near-perfect match for the
other's query, and asserts it is not returned. That is the failure this schema's
`child_id = ...` predicate exists to prevent, and it is invisible to any test
with one child in the database.

Marked `integration`; CI runs these with real postgres.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import text

from app.core.config import Settings, get_settings
from app.core.db import dispose_engine, get_session, init_engine
from app.modules.recommendation.documents import (
    ConfusionFact,
    ProfileFact,
    SessionFactRow,
    SkillFact,
    build_corpus,
)
from app.modules.recommendation.embedding import EMBEDDING_DIM, HashingEmbedder
from app.modules.recommendation.repository import RecommendationRepository

pytestmark = pytest.mark.integration

NOW = dt.datetime(2026, 8, 20, 9, 0, tzinfo=dt.UTC)

INSERT_CAREGIVER = text("""
    INSERT INTO caregivers (id, phone_e164, display_name)
    VALUES (CAST(:id AS uuid), :phone, 'T')
    ON CONFLICT DO NOTHING
""")

INSERT_CHILD = text("""
    INSERT INTO children (id, display_name, date_of_birth, comms_level, max_choices)
    VALUES (CAST(:id AS uuid), :name, DATE '2020-05-01', 'single_words', 2)
""")

INSERT_SKILL = text("""
    INSERT INTO skills (
        id, code, category, label_ar, label_vowelised, label_egy,
        transliteration, phonemes, difficulty_tier, intro_order, alt_text_ar,
        prerequisites
    ) VALUES (
        CAST(:id AS uuid), :code, CAST(:category AS skill_category), :label_ar,
        :label_ar, :label_ar, :code, :code, 1, :intro_order, :label_ar,
        CAST(:prerequisites AS jsonb)
    )
    ON CONFLICT (code) DO NOTHING
""")

#: `modality` is named because 0012 widened the primary key to
#: (child_id, skill_id, modality). An ON CONFLICT clause naming only the first
#: two columns matches no unique constraint and Postgres rejects the statement
#: outright -- which is how the guard's "old code against the new schema"
#: argument shows up in practice, in miniature.
#:
#: `receptive`, because that is the modality every fixture here exercises.
INSERT_STATE = text("""
    INSERT INTO skill_states (child_id, skill_id, modality, state, p_known, due_at)
    VALUES (CAST(:child_id AS uuid), CAST(:skill_id AS uuid), 'receptive',
            CAST(:state AS mastery_state), :p_known, :due_at)
    ON CONFLICT (child_id, skill_id, modality) DO UPDATE SET state = EXCLUDED.state
""")


@pytest.fixture
def settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
async def session(settings: Settings):  # type: ignore[no-untyped-def]
    init_engine(settings)
    agen = get_session()
    active = await anext(agen)
    try:
        yield active
    finally:
        # Rolled back rather than committed. These tests seed children and
        # skills; leaving them behind would make the next run of the suite
        # start from a different database than this one did.
        await active.rollback()
        await active.close()
        await dispose_engine()


async def _seed_child(session, name: str) -> str:  # type: ignore[no-untyped-def]
    caregiver_id = str(uuid.uuid4())
    child_id = str(uuid.uuid4())
    suffix = caregiver_id.replace("-", "")[:9]
    await session.execute(
        INSERT_CAREGIVER,
        {"id": caregiver_id, "phone": f"+2010{suffix}"},
    )
    await session.execute(INSERT_CHILD, {"id": child_id, "name": name})
    return child_id


async def _seed_skill(
    session,  # type: ignore[no-untyped-def]
    *,
    code: str,
    category: str,
    label_ar: str,
    intro_order: int,
) -> str:
    skill_id = str(uuid.uuid4())
    await session.execute(
        INSERT_SKILL,
        {
            "id": skill_id,
            "code": code,
            "category": category,
            "label_ar": label_ar,
            "intro_order": intro_order,
            "prerequisites": "[]",
        },
    )
    row = (
        await session.execute(
            text("SELECT id::text AS id FROM skills WHERE code = :c"), {"c": code}
        )
    ).one()
    return str(row.id)


def _corpus(child_id: str, *, label_ar: str, code: str, skill_id: str):
    return build_corpus(
        child_id,
        profile=ProfileFact("single_words", 8000, 2, 85, False, 8, False, False),
        skills=[
            SkillFact(
                skill_id=skill_id,
                code=code,
                label_ar=label_ar,
                category="colors",
                state="practising",
                p_known=0.6,
                due_at=None,
                updated_at=NOW,
                total_attempts=20,
                total_correct=12,
                independent_attempts=9,
            )
        ],
        sessions=[SessionFactRow("11111111-1111-1111-1111-111111111111", NOW, 7, 14, 9, "fatigue")],
        confusions=[ConfusionFact(code, label_ar, "color_orange", "برتقالي", 4, NOW)],
    )


async def _index(session, child_id: str, documents) -> RecommendationRepository:  # type: ignore[no-untyped-def]
    repository = RecommendationRepository(session)
    embedder = HashingEmbedder()
    await repository.upsert_documents(
        child_id,
        documents,
        embedder.embed_batch([document.text_ar for document in documents]),
        embedder=embedder.name,
    )
    return repository


async def test_a_document_round_trips_through_pgvector(session) -> None:  # type: ignore[no-untyped-def]
    """The vector literal must survive the write and come back rankable."""
    child_id = await _seed_child(session, "أ")
    skill_id = await _seed_skill(
        session, code="color_red_rt", category="colors", label_ar="أحمر", intro_order=1
    )
    documents = _corpus(child_id, label_ar="أحمر", code="color_red_rt", skill_id=skill_id)
    repository = await _index(session, child_id, documents)

    hits = await repository.search(child_id, HashingEmbedder().embed("الألوان"), limit=5)
    assert hits, "pgvector returned nothing for a query that matches the corpus"
    top, score = hits[0]
    assert 0.0 <= score <= 1.0, "1 - cosine distance must land in 0..1"
    assert top.text_ar
    assert top.metadata, "jsonb metadata must survive the round trip"


async def test_search_never_crosses_children(session) -> None:  # type: ignore[no-untyped-def]
    """The failure a single-child test cannot see.

    An ANN scan that found nearest neighbours first and filtered by child second
    would return the other child's document here, because it is the better match
    for the query.
    """
    mine = await _seed_child(session, "أ")
    theirs = await _seed_child(session, "ب")
    skill_id = await _seed_skill(
        session, code="color_red_x", category="colors", label_ar="أحمر", intro_order=1
    )

    repository = await _index(
        session, theirs, _corpus(theirs, label_ar="أحمر", code="color_red_x", skill_id=skill_id)
    )
    await _index(
        session,
        mine,
        build_corpus(
            mine,
            profile=ProfileFact("phrases", 5000, 4, 100, True, 5, True, False),
        ),
    )

    hits = await repository.search(mine, HashingEmbedder().embed("الألوان"), limit=10)
    returned = {document.doc_id for document, _ in hits}
    assert all(doc_id.startswith(mine) for doc_id in returned)
    assert not any(doc_id.startswith(theirs) for doc_id in returned)


async def test_reindexing_updates_in_place_rather_than_accumulating(session) -> None:  # type: ignore[no-untyped-def]
    """Document ids are deterministic, so the write is an upsert."""
    child_id = await _seed_child(session, "أ")
    skill_id = await _seed_skill(
        session, code="color_red_up", category="colors", label_ar="أحمر", intro_order=1
    )
    documents = _corpus(child_id, label_ar="أحمر", code="color_red_up", skill_id=skill_id)

    await _index(session, child_id, documents)
    await _index(session, child_id, documents)

    count = (
        await session.execute(
            text("SELECT count(*) FROM child_memory WHERE child_id = CAST(:c AS uuid)"),
            {"c": child_id},
        )
    ).scalar_one()
    assert count == len(documents)


async def test_prune_removes_what_the_rebuild_no_longer_produces(session) -> None:  # type: ignore[no-untyped-def]
    """A skill that lapses and recovers must not keep its old `lapsed` sentence."""
    child_id = await _seed_child(session, "أ")
    skill_id = await _seed_skill(
        session, code="color_red_pr", category="colors", label_ar="أحمر", intro_order=1
    )
    documents = _corpus(child_id, label_ar="أحمر", code="color_red_pr", skill_id=skill_id)
    repository = await _index(session, child_id, documents)

    keep = [documents[0].doc_id]
    removed = await repository.prune(child_id, keep)
    assert removed == len(documents) - 1

    remaining = await repository.search(child_id, HashingEmbedder().embed("الألوان"), limit=10)
    assert [document.doc_id for document, _ in remaining] == keep


async def test_purge_removes_everything_for_erasure(session) -> None:  # type: ignore[no-untyped-def]
    """The index is derived data and must go with the source."""
    child_id = await _seed_child(session, "أ")
    skill_id = await _seed_skill(
        session, code="color_red_pg", category="colors", label_ar="أحمر", intro_order=1
    )
    repository = await _index(
        session,
        child_id,
        _corpus(child_id, label_ar="أحمر", code="color_red_pg", skill_id=skill_id),
    )
    assert await repository.purge(child_id) > 0
    assert await repository.search(child_id, HashingEmbedder().embed("الألوان")) == []


async def test_snapshots_and_labels_feed_the_candidate_engine(session) -> None:  # type: ignore[no-untyped-def]
    """The SQL the recommendation depends on, against the real schema.

    This is the query that joins `skills` to `skill_states` to the per-skill
    attempt aggregate. Every column it names has to exist -- the class of defect
    that put `relation "skills" does not exist` in front of every running
    instance until migration 0008.
    """
    child_id = await _seed_child(session, "أ")
    skill_id = await _seed_skill(
        session, code="color_red_sn", category="colors", label_ar="أحمر", intro_order=1
    )
    await session.execute(
        INSERT_STATE,
        {
            "child_id": child_id,
            "skill_id": skill_id,
            "state": "lapsed",
            "p_known": 0.5,
            "due_at": NOW,
        },
    )
    repository = RecommendationRepository(session)
    snapshots, labels = await repository.snapshots_and_labels(child_id)

    assert snapshots, "the catalogue must produce at least one snapshot"
    assert labels[skill_id] == ("color_red_sn", "أحمر")
    mine = next(s for s in snapshots if s.skill_id == skill_id)
    assert mine.state.value == "lapsed"


async def test_history_reads_return_empty_rather_than_failing(session) -> None:  # type: ignore[no-untyped-def]
    """A child with no play history is the first-run state, not an error.

    Each of these is a different table and a different join; a missing column in
    any of them would surface here rather than on a caregiver's first session.
    """
    child_id = await _seed_child(session, "أ")
    repository = RecommendationRepository(session)

    assert await repository.profile(child_id) is not None
    assert await repository.sessions(child_id) == []
    assert await repository.confusions(child_id, now=NOW) == []
    assert await repository.milestones(child_id) == []


async def test_the_embedding_column_width_matches_the_module(session) -> None:  # type: ignore[no-untyped-def]
    """The migration imports EMBEDDING_DIM; this asserts the database agrees.

    A mismatch is an insert that fails at runtime, and the number is written in
    two places only if somebody edits one of them.
    """
    dimensions = (
        await session.execute(
            text("""
                SELECT atttypmod FROM pg_attribute
                WHERE attrelid = 'child_memory'::regclass AND attname = 'embedding'
            """)
        )
    ).scalar_one()
    assert dimensions == EMBEDDING_DIM


async def test_the_ai_cannot_grant_constraint_is_enforced_by_the_database(session) -> None:  # type: ignore[no-untyped-def]
    """Principle P2, asserted against Postgres rather than against the DDL text.

    P07 has wanted this since it was written: the application rule is tested,
    the database backstop was not. An AI verdict cannot promote a child to
    `mastered` without the deterministic rule being satisfied, even if
    application code tries.
    """
    from sqlalchemy.exc import IntegrityError

    child_id = await _seed_child(session, "أ")
    skill_id = await _seed_skill(
        session, code="color_red_cn", category="colors", label_ar="أحمر", intro_order=1
    )
    caregiver = (
        await session.execute(text("SELECT id::text AS id FROM caregivers LIMIT 1"))
    ).one()
    play_session = (
        await session.execute(
            text("""
                INSERT INTO play_sessions (child_id, started_by)
                VALUES (CAST(:c AS uuid), CAST(:g AS uuid))
                RETURNING id::text AS id
            """),
            {"c": child_id, "g": caregiver.id},
        )
    ).one()

    with pytest.raises(IntegrityError):
        await session.execute(
            text("""
                INSERT INTO mastery_events (
                    child_id, skill_id, from_state, to_state,
                    p_known_at_event, rule_satisfied, ai_verdict, session_id
                ) VALUES (
                    CAST(:c AS uuid), CAST(:s AS uuid), 'practising', 'mastered',
                    0.99, false, 'confirm', CAST(:sess AS uuid)
                )
            """),
            {"c": child_id, "s": skill_id, "sess": play_session.id},
        )
