"""SQL for the retrieval corpus and the history it is built from.

Every read here is scoped to one child in the WHERE clause, not filtered after
the fact. That is not a performance note: `child_memory` holds one row per
document for every child in the system, and an ANN index scan that finds the
nearest neighbours *first* and applies the child filter *second* would return
another child's history whenever this child has fewer than `k` documents. The
`child_id = ...` predicate is inside the same query as the `<=>` ordering for
exactly that reason.

The aggregates are computed in Postgres rather than in Python because they are
computed over every attempt a child has ever made, and the alternative is
shipping that history over the wire once per recommendation.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping, Sequence
from typing import Any, cast

import structlog
from sqlalchemy import CursorResult, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.learning.domain.candidates import SkillSnapshot
from app.modules.learning.domain.mastery import MasteryState
from app.modules.recommendation.documents import (
    ConfusionFact,
    MemoryDocument,
    MilestoneFact,
    ProfileFact,
    SessionFactRow,
    SkillFact,
)

logger = structlog.get_logger(__name__)

#: How far back a confusion pattern is read. Beyond this a child has usually
#: moved on, and a stale confusion is worse than none -- it sends a caregiver
#: back to a problem that resolved itself weeks ago.
CONFUSION_WINDOW_DAYS = 45

#: Sessions retrieved for the corpus. Twelve is roughly a fortnight of daily
#: play; older sessions are already summarised in `progress_rollups`.
SESSION_LIMIT = 12

MILESTONE_LIMIT = 20


SELECT_PROFILE = text("""
    SELECT comms_level::text AS comms_level,
           wait_time_ms, max_choices, audio_rate_pct,
           calm_mode, session_minutes, hearing_aid, glasses
    FROM children
    WHERE id = CAST(:child_id AS uuid) AND archived_at IS NULL
""")

#: skills LEFT JOIN skill_states, with the per-skill attempt aggregates folded
#: in. LEFT JOIN on the aggregate too: a skill with a state row and no attempts
#: is a real state (seeded from an assessment), and an INNER JOIN would drop it.
SELECT_SKILLS = text("""
    WITH agg AS (
        SELECT skill_id,
               count(*)                                          AS total_attempts,
               count(*) FILTER (WHERE result = 'correct')         AS total_correct,
               count(*) FILTER (WHERE prompt_level = 'independent') AS independent
        FROM attempts
        WHERE child_id = CAST(:child_id AS uuid)
        GROUP BY skill_id
    )
    SELECT s.id::text        AS skill_id,
           s.code,
           s.label_ar,
           s.category::text  AS category,
           s.difficulty_tier,
           s.intro_order,
           s.prerequisites,
           COALESCE(st.state::text, 'not_started') AS state,
           COALESCE(st.p_known, 0.0)               AS p_known,
           st.due_at,
           st.updated_at,
           COALESCE(agg.total_attempts, 0) AS total_attempts,
           COALESCE(agg.total_correct, 0)  AS total_correct,
           COALESCE(agg.independent, 0)    AS independent
    FROM skills s
    LEFT JOIN skill_states st
           ON st.skill_id = s.id AND st.child_id = CAST(:child_id AS uuid)
    LEFT JOIN agg ON agg.skill_id = s.id
    WHERE s.is_active
    ORDER BY s.category, s.intro_order
""")

SELECT_SESSIONS = text("""
    SELECT id::text AS session_id, started_at,
           GREATEST(0, EXTRACT(EPOCH FROM (COALESCE(ended_at, started_at) - started_at))
                       / 60)::int AS minutes,
           activities_done AS attempts,
           correct_count   AS correct,
           ended_reason
    FROM play_sessions
    WHERE child_id = CAST(:child_id AS uuid)
    ORDER BY started_at DESC
    LIMIT :limit
""")

#: The same wrong choice, counted. `selected_skill_id <> skill_id` excludes the
#: correct taps; `IS NOT NULL` excludes expressive attempts, where there is no
#: choice to have confused anything with.
SELECT_CONFUSIONS = text("""
    SELECT target.code   AS skill_code,
           target.label_ar AS label_ar,
           chosen.code    AS confused_with_code,
           chosen.label_ar AS confused_with_label_ar,
           count(*)       AS occurrences,
           max(a.created_at) AS last_at
    FROM attempts a
    JOIN skills target ON target.id = a.skill_id
    JOIN skills chosen ON chosen.id = a.selected_skill_id
    WHERE a.child_id = CAST(:child_id AS uuid)
      AND a.selected_skill_id IS NOT NULL
      AND a.selected_skill_id <> a.skill_id
      AND a.created_at >= :since
    GROUP BY target.code, target.label_ar, chosen.code, chosen.label_ar
    HAVING count(*) >= :min_occurrences
    ORDER BY count(*) DESC, target.code
""")

SELECT_MILESTONES = text("""
    SELECT s.code AS skill_code, s.label_ar,
           m.from_state::text AS from_state,
           m.to_state::text   AS to_state,
           m.created_at       AS at
    FROM mastery_events m
    JOIN skills s ON s.id = m.skill_id
    WHERE m.child_id = CAST(:child_id AS uuid)
      AND m.to_state IN ('mastered', 'retained', 'lapsed')
    ORDER BY m.created_at DESC
    LIMIT :limit
""")

UPSERT_DOCUMENT = text("""
    INSERT INTO child_memory (
        doc_id, child_id, kind, text_ar, occurred_at, metadata,
        embedding, embedder, updated_at
    ) VALUES (
        :doc_id, CAST(:child_id AS uuid), :kind, :text_ar, :occurred_at,
        CAST(:metadata AS jsonb), CAST(:embedding AS vector), :embedder, now()
    )
    ON CONFLICT (doc_id) DO UPDATE SET
        kind        = EXCLUDED.kind,
        text_ar     = EXCLUDED.text_ar,
        occurred_at = EXCLUDED.occurred_at,
        metadata    = EXCLUDED.metadata,
        embedding   = EXCLUDED.embedding,
        embedder    = EXCLUDED.embedder,
        updated_at  = now()
""")

#: `1 - (embedding <=> query)` turns cosine DISTANCE into cosine SIMILARITY, so
#: the score this returns is directly comparable to `embedding.cosine` and to
#: the in-memory fallback. Ordering is on the distance operator, not on the
#: derived similarity, because only the operator form uses the HNSW index.
SEARCH = text("""
    SELECT doc_id, kind, text_ar, occurred_at, metadata,
           1 - (embedding <=> CAST(:query AS vector)) AS score
    FROM child_memory
    WHERE child_id = CAST(:child_id AS uuid)
    ORDER BY embedding <=> CAST(:query AS vector)
    LIMIT :limit
""")

PRUNE = text("""
    DELETE FROM child_memory
    WHERE child_id = CAST(:child_id AS uuid)
      AND doc_id <> ALL(:keep)
""")

PURGE = text("DELETE FROM child_memory WHERE child_id = CAST(:child_id AS uuid)")


def vector_literal(vector: Sequence[float]) -> str:
    """pgvector's text input form.

    `repr` on a Python float round-trips exactly; `str` on numpy scalars does
    not, and a silently truncated coordinate is a vector that no longer matches
    the one the same text produced yesterday.
    """
    return "[" + ",".join(repr(float(component)) for component in vector) + "]"


class RecommendationRepository:
    """Reads history, writes the index, searches it."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- history reads ------------------------------------------------------

    async def profile(self, child_id: str) -> ProfileFact | None:
        row = (await self._session.execute(SELECT_PROFILE, {"child_id": child_id})).first()
        if row is None:
            return None
        return ProfileFact(
            comms_level=row.comms_level,
            wait_time_ms=int(row.wait_time_ms),
            max_choices=int(row.max_choices),
            audio_rate_pct=int(row.audio_rate_pct),
            calm_mode=bool(row.calm_mode),
            session_minutes=int(row.session_minutes),
            hearing_aid=bool(row.hearing_aid),
            glasses=bool(row.glasses),
        )

    async def skill_rows(self, child_id: str) -> list[Any]:
        return list(await self._session.execute(SELECT_SKILLS, {"child_id": child_id}))

    async def skills(self, child_id: str) -> list[SkillFact]:
        return [_skill_fact(row) for row in await self.skill_rows(child_id)]

    async def sessions(self, child_id: str, *, limit: int = SESSION_LIMIT) -> list[SessionFactRow]:
        rows = await self._session.execute(
            SELECT_SESSIONS, {"child_id": child_id, "limit": limit}
        )
        return [
            SessionFactRow(
                session_id=str(row.session_id),
                started_at=row.started_at,
                minutes=int(row.minutes),
                attempts=int(row.attempts),
                correct=int(row.correct),
                ended_reason=row.ended_reason,
            )
            for row in rows
        ]

    async def confusions(
        self,
        child_id: str,
        *,
        now: dt.datetime | None = None,
        min_occurrences: int = 3,
    ) -> list[ConfusionFact]:
        since = (now or dt.datetime.now(dt.UTC)) - dt.timedelta(days=CONFUSION_WINDOW_DAYS)
        rows = await self._session.execute(
            SELECT_CONFUSIONS,
            {"child_id": child_id, "since": since, "min_occurrences": min_occurrences},
        )
        return [
            ConfusionFact(
                skill_code=row.skill_code,
                label_ar=row.label_ar,
                confused_with_code=row.confused_with_code,
                confused_with_label_ar=row.confused_with_label_ar,
                occurrences=int(row.occurrences),
                last_at=row.last_at,
            )
            for row in rows
        ]

    async def milestones(
        self, child_id: str, *, limit: int = MILESTONE_LIMIT
    ) -> list[MilestoneFact]:
        rows = await self._session.execute(
            SELECT_MILESTONES, {"child_id": child_id, "limit": limit}
        )
        return [
            MilestoneFact(
                skill_code=row.skill_code,
                label_ar=row.label_ar,
                from_state=row.from_state,
                to_state=row.to_state,
                at=row.at,
            )
            for row in rows
        ]

    # --- the candidate engine's inputs --------------------------------------

    async def snapshots_and_labels(
        self, child_id: str
    ) -> tuple[list[SkillSnapshot], dict[str, tuple[str, str]]]:
        """What `candidates()` needs, plus the labels the caregiver sees.

        Prerequisites are stored as skill *codes* (0008) and the engine wants
        *ids*, so the resolution happens here against the same result set rather
        than as a second query -- the catalogue is 88 rows and already in hand.
        A prerequisite naming a code that does not exist is dropped rather than
        raised on: an unsatisfiable prerequisite would make the skill
        permanently ineligible, which is a worse failure than ignoring a typo in
        the seed data.
        """
        rows = await self.skill_rows(child_id)
        by_code = {row.code: row.skill_id for row in rows}
        snapshots: list[SkillSnapshot] = []
        labels: dict[str, tuple[str, str]] = {}
        for row in rows:
            labels[row.skill_id] = (row.code, row.label_ar)
            prerequisites = tuple(
                by_code[code]
                for code in _as_list(row.prerequisites)
                if code in by_code
            )
            snapshots.append(
                SkillSnapshot(
                    skill_id=row.skill_id,
                    # Receptive is the only modality the child app can render
                    # today; `content/` has no activity table to say otherwise.
                    modality="receptive",
                    state=MasteryState(row.state),
                    due_at=row.due_at,
                    intro_order=int(row.intro_order),
                    difficulty_tier=int(row.difficulty_tier),
                    prerequisites=prerequisites,
                )
            )
        return snapshots, labels

    # --- the index ----------------------------------------------------------

    async def upsert_documents(
        self,
        child_id: str,
        documents: Sequence[MemoryDocument],
        vectors: Sequence[Sequence[float]],
        *,
        embedder: str,
    ) -> int:
        if len(documents) != len(vectors):
            raise ValueError("documents and vectors must be the same length")
        for document, vector in zip(documents, vectors, strict=True):
            await self._session.execute(
                UPSERT_DOCUMENT,
                {
                    "doc_id": document.doc_id,
                    "child_id": child_id,
                    "kind": document.kind.value,
                    "text_ar": document.text_ar,
                    "occurred_at": document.occurred_at,
                    "metadata": json.dumps(document.metadata, ensure_ascii=False),
                    "embedding": vector_literal(vector),
                    "embedder": embedder,
                },
            )
        return len(documents)

    async def prune(self, child_id: str, keep: Sequence[str]) -> int:
        """Remove documents the rebuild no longer produces.

        Without this a skill that lapses and then recovers leaves its old
        `lapsed` sentence in the index forever, and retrieval keeps surfacing a
        problem that no longer exists.
        """
        result = await self._session.execute(
            PRUNE, {"child_id": child_id, "keep": list(keep) or [""]}
        )
        return int(cast("CursorResult[Any]", result).rowcount or 0)

    async def purge(self, child_id: str) -> int:
        """Erasure. Called by the same walk that deletes the child's audio."""
        result = await self._session.execute(PURGE, {"child_id": child_id})
        return int(cast("CursorResult[Any]", result).rowcount or 0)

    async def search(
        self, child_id: str, query: Sequence[float], *, limit: int = 8
    ) -> list[tuple[MemoryDocument, float]]:
        rows = await self._session.execute(
            SEARCH,
            {"child_id": child_id, "query": vector_literal(query), "limit": limit},
        )
        return [(_document(row), float(row.score)) for row in rows]


def _as_list(value: Any) -> list[str]:
    """jsonb arrives as a list; a text column would arrive as a JSON string."""
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str) and value:
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return []
        return [str(item) for item in loaded] if isinstance(loaded, list) else []
    return []


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str) and value:
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(loaded) if isinstance(loaded, dict) else {}
    return {}


def _skill_fact(row: Any) -> SkillFact:
    return SkillFact(
        skill_id=row.skill_id,
        code=row.code,
        label_ar=row.label_ar,
        category=row.category,
        state=row.state,
        p_known=float(row.p_known),
        due_at=row.due_at,
        updated_at=row.updated_at,
        total_attempts=int(row.total_attempts),
        total_correct=int(row.total_correct),
        independent_attempts=int(row.independent),
    )


def _document(row: Any) -> MemoryDocument:
    from app.modules.recommendation.documents import DocumentKind

    return MemoryDocument(
        doc_id=row.doc_id,
        kind=DocumentKind(row.kind),
        text_ar=row.text_ar,
        occurred_at=row.occurred_at,
        metadata=_as_dict(row.metadata),
    )


__all__ = [
    "CONFUSION_WINDOW_DAYS",
    "MILESTONE_LIMIT",
    "SESSION_LIMIT",
    "RecommendationRepository",
    "vector_literal",
]
