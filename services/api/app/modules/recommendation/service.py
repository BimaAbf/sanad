"""The recommendation service — indexing, retrieval and the next-exercise call.

Two entry points and one rule that connects them.

`reindex` rebuilds a child's retrieval corpus from their database history. It is
idempotent: document ids are deterministic (`documents.py`), the write is an
upsert, and anything the rebuild no longer produces is pruned in the same
transaction. Running it twice changes nothing; running it never means retrieval
returns an empty list and the recommendation falls back to the engine.

`next_exercise` runs the graph. The rule that connects them is that **an empty
or stale index degrades the answer, it never breaks it** -- the deterministic
candidate engine produces a recommendation with no retrieval at all.

Consent is checked before the model is reached, not after. Without
`ai_processing` the judge is not constructed at all -- the graph is built with
`runnable=None`, so there is no code path on which a payload is assembled for a
child whose caregiver has not agreed to it. Checking after assembly would leave
a window in which the data exists; checking by not building the runnable means
the window does not exist.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any, cast

import structlog
from langchain_core.documents import Document

from app.ai.langchain import GatewayRunnable
from app.modules.children.domain import ConsentKey
from app.modules.recommendation.documents import MemoryDocument, build_corpus
from app.modules.recommendation.embedding import Embedder, HashingEmbedder
from app.modules.recommendation.graph import build_graph, gateway_call
from app.modules.recommendation.judge import Recommendation
from app.modules.recommendation.repository import RecommendationRepository
from app.modules.recommendation.retriever import ChildMemoryRetriever
from app.modules.voice.service import ConsentReader

logger = structlog.get_logger(__name__)


class RecommendationService:
    def __init__(
        self,
        *,
        repository: RecommendationRepository,
        consent: ConsentReader,
        gateway: Any | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self._repository = repository
        self._consent = consent
        self._gateway = gateway
        self._embedder = embedder or HashingEmbedder()

    # --- indexing -----------------------------------------------------------

    async def build_documents(
        self, child_id: str, *, now: dt.datetime | None = None
    ) -> list[MemoryDocument]:
        """Read the history, build the corpus. No writes, so a caller can diff."""
        moment = now or dt.datetime.now(dt.UTC)
        return build_corpus(
            child_id,
            profile=await self._repository.profile(child_id),
            skills=await self._repository.skills(child_id),
            sessions=await self._repository.sessions(child_id),
            confusions=await self._repository.confusions(child_id, now=moment),
            milestones=await self._repository.milestones(child_id),
        )

    async def reindex(self, child_id: str, *, now: dt.datetime | None = None) -> int:
        """Rebuild and prune. Returns the number of documents now indexed."""
        documents = await self.build_documents(child_id, now=now)
        vectors = self._embedder.embed_batch([document.text_ar for document in documents])
        await self._repository.upsert_documents(
            child_id, documents, vectors, embedder=self._embedder.name
        )
        removed = await self._repository.prune(
            child_id, [document.doc_id for document in documents]
        )
        logger.info(
            "memory_reindexed",
            child_id=child_id,
            count=len(documents),
            pruned=removed,
            embedder=self._embedder.name,
        )
        return len(documents)

    async def purge(self, child_id: str) -> int:
        """Erasure. The index is derived data and must go with the source."""
        return await self._repository.purge(child_id)

    # --- retrieval ----------------------------------------------------------

    def retriever(self, child_id: str, *, k: int = 8) -> ChildMemoryRetriever:
        return ChildMemoryRetriever(
            repository=self._repository,
            child_id=child_id,
            embedder=self._embedder,
            k=k,
        )

    async def search(self, child_id: str, query: str, *, k: int = 8) -> list[Document]:
        return await self.retriever(child_id, k=k).ainvoke(query)

    # --- the recommendation -------------------------------------------------

    async def _runnable(self, child_id: str) -> GatewayRunnable | None:
        if self._gateway is None:
            return None
        if not await self._consent.is_granted(child_id, ConsentKey.AI_PROCESSING):
            logger.info("recommendation_ai_skipped", child_id=child_id, reason="no_consent")
            return None
        return GatewayRunnable(self._gateway, gateway_call())

    async def next_exercise(
        self, child_id: str, *, now: dt.datetime | None = None, limit: int = 8
    ) -> Recommendation | None:
        """The next best exercise, whichever path produced it.

        `None` means this child has no eligible skill at all -- an empty
        catalogue, or every skill already retained. That is a real state with a
        real screen (the caregiver app's empty state), not an error.
        """
        snapshots, labels = await self._repository.snapshots_and_labels(child_id)
        if not snapshots:
            logger.info("recommendation_no_catalogue", child_id=child_id)
            return None
        graph = build_graph(
            retriever=self.retriever(child_id),
            runnable=await self._runnable(child_id),
            limit=limit,
        )
        state = await graph.ainvoke(
            {
                "child_id": child_id,
                "now": now or dt.datetime.now(dt.UTC),
                "snapshots": snapshots,
                "labels": labels,
                "trace": [],
            }
        )
        return cast("Recommendation | None", state.get("recommendation"))


def documents_as_rows(documents: Sequence[Document]) -> list[dict[str, Any]]:
    """Retrieved documents in the shape the console route returns."""
    return [
        {
            "doc_id": str(document.metadata.get("doc_id", "")),
            "kind": str(document.metadata.get("kind", "")),
            "at": str(document.metadata.get("at", "")),
            "score": float(document.metadata.get("score", 0.0)),
            "text_ar": document.page_content,
        }
        for document in documents
    ]


__all__ = ["RecommendationService", "documents_as_rows"]
