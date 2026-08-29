"""Embedding, corpus construction, retrieval and the next-exercise judge.

The tests worth reading first are the ones that assert a *refusal*:
`test_invented_skill_id_falls_back`, `test_duplicate_in_plan_falls_back` and
`test_two_new_skills_falls_back`. Those three are the safety property of this
whole module -- the model may reorder what the deterministic engine offered and
may never add to it -- and each of them describes a plausible model answer, not
a contrived one.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.modules.learning.domain.candidates import Candidate, CandidateKind, SkillSnapshot
from app.modules.learning.domain.mastery import MasteryState
from app.modules.recommendation.documents import (
    ConfusionFact,
    DocumentKind,
    MilestoneFact,
    ProfileFact,
    SessionFactRow,
    SkillFact,
    build_corpus,
    forbidden_fields_present,
)
from app.modules.recommendation.embedding import (
    EMBEDDING_DIM,
    HashingEmbedder,
    cosine,
    tokens,
    top_k,
)
from app.modules.recommendation.judge import (
    MAX_NEW_IN_PLAN,
    NextExercisePlan,
    apply,
    deterministic_recommendation,
)
from app.modules.recommendation.repository import vector_literal
from app.modules.recommendation.retriever import InMemoryChildMemoryRetriever

NOW = dt.datetime(2026, 8, 20, 9, 0, tzinfo=dt.UTC)

RED = SkillFact(
    skill_id="s-red",
    code="color_red",
    label_ar="أحمر",
    category="colors",
    state="practising",
    p_known=0.62,
    due_at=None,
    updated_at=NOW,
    total_attempts=20,
    total_correct=12,
    independent_attempts=9,
)
BRUSH = SkillFact(
    skill_id="s-brush",
    code="hh_toothbrush",
    label_ar="فرشاة سنان",
    category="household",
    state="introduced",
    p_known=0.30,
    due_at=None,
    updated_at=NOW,
    total_attempts=5,
    total_correct=2,
    independent_attempts=1,
)
UNTOUCHED = SkillFact(
    skill_id="s-nine",
    code="num_9",
    label_ar="تسعة",
    category="numbers",
    state="not_started",
    p_known=0.0,
    due_at=None,
    updated_at=None,
)

PROFILE = ProfileFact(
    comms_level="single_words",
    wait_time_ms=8000,
    max_choices=2,
    audio_rate_pct=85,
    calm_mode=False,
    session_minutes=8,
    hearing_aid=False,
    glasses=False,
)


# --- embedding --------------------------------------------------------------


def test_embedding_is_unit_length_and_right_width() -> None:
    vector = HashingEmbedder().embed("أحمر وأزرق")
    assert len(vector) == EMBEDDING_DIM
    assert sum(component * component for component in vector) == pytest.approx(1.0)


def test_embedding_is_deterministic_across_instances() -> None:
    """Two processes must produce the same vector for the same text.

    This is the reason `_bucket` uses blake2b rather than the builtin `hash()`.
    If it regresses, the ingest worker and the API land in different vector
    spaces and retrieval quietly returns nothing relevant.
    """
    assert HashingEmbedder().embed("أحمر") == HashingEmbedder().embed("أحمر")


def test_empty_text_embeds_to_zero_rather_than_nan() -> None:
    vector = HashingEmbedder().embed("   ")
    assert set(vector) == {0.0}
    assert cosine(vector, HashingEmbedder().embed("أحمر")) == 0.0


def test_related_text_scores_above_unrelated() -> None:
    embedder = HashingEmbedder()
    about_colours = embedder.embed("مهارة «أحمر» (ألوان): بيتدرب عليها.")
    colour_query = embedder.embed("الألوان")
    brushing = embedder.embed("مهارة «فرشاة سنان» (أدوات البيت): اتعرّف عليها.")
    assert cosine(about_colours, colour_query) > cosine(brushing, colour_query)


def test_normalisation_makes_hamza_forms_equivalent() -> None:
    """أ and ا are the same sound and ASR is unreliable about which it emits."""
    embedder = HashingEmbedder()
    assert embedder.embed("أحمر") == embedder.embed("احمر")


def test_tokens_include_words_and_ngrams() -> None:
    produced = tokens("أحمر")
    assert any(token.startswith("w:") for token in produced)
    assert any(token.startswith("g:") for token in produced)


def test_top_k_orders_by_similarity_and_respects_the_floor() -> None:
    embedder = HashingEmbedder()
    corpus = [
        ("a", embedder.embed("أحمر")),
        ("b", embedder.embed("فرشاة سنان")),
    ]
    ranked = top_k(embedder.embed("أحمر"), corpus, k=2, floor=0.5)
    assert [identifier for identifier, _ in ranked] == ["a"]


def test_cosine_rejects_a_dimension_mismatch() -> None:
    with pytest.raises(ValueError, match="dimension mismatch"):
        cosine([1.0, 0.0], [1.0, 0.0, 0.0])


def test_vector_literal_round_trips_exactly() -> None:
    """A truncated coordinate is a vector that stops matching yesterday's."""
    vector = HashingEmbedder().embed("أحمر")
    parsed = [float(part) for part in vector_literal(vector)[1:-1].split(",")]
    assert parsed == vector


# --- documents --------------------------------------------------------------


def test_corpus_skips_untouched_skills() -> None:
    """88 identical "has not started" sentences would crowd out the real ones."""
    corpus = build_corpus("c1", skills=[RED, UNTOUCHED])
    codes = {document.metadata.get("skill_code") for document in corpus}
    assert "color_red" in codes
    assert "num_9" not in codes


def test_corpus_carries_no_forbidden_field() -> None:
    corpus = build_corpus(
        "c1",
        profile=PROFILE,
        skills=[RED, BRUSH],
        sessions=[SessionFactRow("sess-1", NOW, 7, 14, 9, "fatigue")],
        confusions=[ConfusionFact("color_red", "أحمر", "color_orange", "برتقالي", 4, NOW)],
        milestones=[MilestoneFact("color_red", "أحمر", "practising", "mastered", NOW)],
    )
    assert forbidden_fields_present(corpus) == []


def test_skill_document_keeps_p_known_out_of_the_text() -> None:
    """docs/04a forbids showing a caregiver a mastery percentage.

    The caregiver-facing chat reads document TEXT back. `p_known` stays in
    metadata, where only the judge sees it.
    """
    document = build_corpus("c1", skills=[RED])[0]
    assert "0.62" not in document.text_ar
    assert document.metadata["p_known"] == pytest.approx(0.62)


def test_a_weak_confusion_is_not_indexed() -> None:
    """One wrong tap is a random tap; the threshold is what makes it a pattern."""
    corpus = build_corpus(
        "c1", confusions=[ConfusionFact("color_red", "أحمر", "color_orange", "برتقالي", 2, NOW)]
    )
    assert corpus == []


def test_document_ids_are_stable_across_rebuilds() -> None:
    """The upsert key. Unstable ids mean the index grows a copy every night."""
    first = build_corpus("c1", profile=PROFILE, skills=[RED])
    second = build_corpus("c1", profile=PROFILE, skills=[RED])
    assert [d.doc_id for d in first] == [d.doc_id for d in second]


def test_fatigue_is_recorded_in_the_session_document() -> None:
    corpus = build_corpus("c1", sessions=[SessionFactRow("sess-1", NOW, 6, 9, 4, "fatigue")])
    assert corpus[0].kind is DocumentKind.SESSION
    assert "تعب" in corpus[0].text_ar


# --- retrieval --------------------------------------------------------------


async def test_retriever_returns_the_relevant_document_first() -> None:
    corpus = build_corpus("c1", profile=PROFILE, skills=[RED, BRUSH])
    retriever = InMemoryChildMemoryRetriever(documents=corpus)
    hits = await retriever.ainvoke("إيه أخبار الألوان؟")
    assert hits
    assert hits[0].metadata.get("skill_code") == "color_red"


async def test_retriever_returns_nothing_for_an_unrelated_query() -> None:
    """An unrelated document is worse than none: the model treats what it is
    given as relevant, which is how a grounded answer becomes a confident wrong
    one."""
    retriever = InMemoryChildMemoryRetriever(documents=build_corpus("c1", skills=[RED]))
    assert await retriever.ainvoke("qwerty zxcvbn") == []


# --- the judge --------------------------------------------------------------

CANDIDATES = [
    Candidate("s-red", "receptive", CandidateKind.LAPSED, 0),
    Candidate("s-blue", "receptive", CandidateKind.DUE, 0),
    Candidate("s-nine", "receptive", CandidateKind.NEW, 0),
    Candidate("s-eye", "receptive", CandidateKind.CONFIDENCE, 0),
]
LABELS = {
    "s-red": ("color_red", "أحمر"),
    "s-blue": ("color_blue", "أزرق"),
    "s-nine": ("num_9", "تسعة"),
    "s-eye": ("body_eye", "عين"),
}


def test_a_valid_reordering_is_accepted() -> None:
    plan = NextExercisePlan(
        ordered_skill_ids=["s-eye", "s-red", "s-blue"],
        reason_ar="نبدأ بحاجة بيعرفها كويس.",
    )
    result = apply(plan, CANDIDATES, LABELS)
    assert result is not None
    assert result.source == "ai"
    assert result.skill_code == "body_eye"


def test_invented_skill_id_falls_back() -> None:
    """An id outside the candidate set means the model invented an activity."""
    plan = NextExercisePlan(ordered_skill_ids=["s-invented"], reason_ar="حاجة.")
    result = apply(plan, CANDIDATES, LABELS)
    assert result is not None
    assert result.source == "deterministic_fallback"
    assert [event.layer for event in result.events] == ["allowlist"]


def test_duplicate_in_plan_falls_back() -> None:
    """A duplicate would show a child the same activity twice in a row."""
    plan = NextExercisePlan(ordered_skill_ids=["s-red", "s-red"], reason_ar="حاجة.")
    result = apply(plan, CANDIDATES, LABELS)
    assert result is not None
    assert result.source == "deterministic_fallback"


def test_two_new_skills_falls_back() -> None:
    """Two new skills in one session is the interference failure docs/04c §C06
    exists to prevent. The engine guarantees at most one, so a plan holding two
    is not a subset of what was offered."""
    candidates = [*CANDIDATES, Candidate("s-ten", "receptive", CandidateKind.NEW, 1)]
    labels = {**LABELS, "s-ten": ("num_10", "عشرة")}
    plan = NextExercisePlan(ordered_skill_ids=["s-nine", "s-ten"], reason_ar="حاجة.")
    result = apply(plan, candidates, labels)
    assert result is not None
    assert result.source == "deterministic_fallback"
    assert MAX_NEW_IN_PLAN == 1


def test_no_plan_at_all_still_recommends() -> None:
    """The gateway returns None for a missing fixture, an exhausted budget, a
    refusal, a timeout and a schema mismatch alike. All five land here."""
    result = apply(None, CANDIDATES, LABELS)
    assert result is not None
    assert result.source == "deterministic_fallback"
    assert result.skill_code == "color_red"


def test_a_candidate_with_no_label_is_skipped_not_rendered() -> None:
    """A caregiver shown a uuid has been shown a bug."""
    result = deterministic_recommendation(CANDIDATES, {"s-blue": ("color_blue", "أزرق")})
    assert result is not None
    assert result.skill_code == "color_blue"


def test_no_candidates_means_no_recommendation() -> None:
    assert deterministic_recommendation([], LABELS) is None


# --- the graph --------------------------------------------------------------


SNAPSHOTS = [
    SkillSnapshot("s-red", "receptive", MasteryState.LAPSED, None, 1, 1),
    SkillSnapshot("s-blue", "receptive", MasteryState.PRACTISING, NOW, 2, 1),
    SkillSnapshot("s-nine", "receptive", MasteryState.NOT_STARTED, None, 3, 2),
    SkillSnapshot("s-eye", "receptive", MasteryState.MASTERED, None, 4, 1),
]


async def test_graph_recommends_with_no_model_at_all() -> None:
    """`runnable=None` is the flag-off deployment, not a test affordance.

    It must produce the same shape of answer as the path where the model
    refused, and it must terminate in a real recommendation.
    """
    from app.modules.recommendation.graph import build_graph

    graph = build_graph(
        retriever=InMemoryChildMemoryRetriever(documents=build_corpus("c1", skills=[RED])),
        runnable=None,
    )
    state = await graph.ainvoke(
        {"child_id": "c1", "now": NOW, "snapshots": SNAPSHOTS, "labels": LABELS, "trace": []}
    )
    recommendation = state["recommendation"]
    assert recommendation.source == "deterministic_fallback"
    assert "judge=skipped" in state["trace"]


async def test_graph_records_what_it_retrieved_even_when_it_falls_back() -> None:
    """A recommendation nobody can review after the fact is not reviewable."""
    from app.modules.recommendation.graph import build_graph

    graph = build_graph(
        retriever=InMemoryChildMemoryRetriever(
            documents=build_corpus("c1", profile=PROFILE, skills=[RED])
        ),
        runnable=None,
    )
    state = await graph.ainvoke(
        {"child_id": "c1", "now": NOW, "snapshots": SNAPSHOTS, "labels": LABELS, "trace": []}
    )
    assert state["recommendation"].grounded_in
