"""The retriever — LangChain's interface over `child_memory`.

Two implementations of one interface, and both are load-bearing:

* `ChildMemoryRetriever` searches pgvector. This is the product.
* `InMemoryChildMemoryRetriever` searches a list. This is how the whole
  recommendation and chat path is tested without a database, which is the same
  arrangement `NullAsr` and `FixtureStore` already provide for the other two
  external dependencies. A retrieval path that can only be exercised against
  live Postgres is a retrieval path that is exercised rarely.

Both are `BaseRetriever` subclasses, so they compose into LCEL chains and
LangGraph nodes exactly like any other retriever, and neither can reach a model:
retrieval reads the index and stops.

**Retrieval here is always child-scoped and never cross-child.** The child id is
a constructor argument rather than a query parameter, so there is no call
signature that even expresses "search everybody" -- which is the failure this
design is guarding against, and the reason the filter is not merely a WHERE
clause somebody remembered to add.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import structlog
from langchain_core.callbacks import (
    AsyncCallbackManagerForRetrieverRun,
    CallbackManagerForRetrieverRun,
)
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field

from app.modules.recommendation.documents import MemoryDocument
from app.modules.recommendation.embedding import Embedder, HashingEmbedder, top_k
from app.modules.recommendation.repository import RecommendationRepository

logger = structlog.get_logger(__name__)

#: Documents returned per query. Eight short Arabic sentences is roughly 250
#: tokens -- enough context to ground an answer, small enough that the frozen
#: prefix still dominates the prompt on a provider with no caching (docs/12 §1).
DEFAULT_K = 8

#: Below this cosine similarity a document is not about the question. Returning
#: it anyway is worse than returning nothing: the model treats whatever it is
#: given as relevant, and an unrelated document is how a grounded answer becomes
#: a confidently wrong one.
DEFAULT_FLOOR = 0.05


class SyncRetrievalNotSupportedError(RuntimeError):
    """Raised by the sync path. The repository is async all the way down."""


def to_langchain(document: MemoryDocument, score: float) -> Document:
    return Document(
        page_content=document.text_ar,
        metadata={
            "doc_id": document.doc_id,
            "kind": document.kind.value,
            "at": document.occurred_at.date().isoformat() if document.occurred_at else "",
            "score": round(score, 4),
            **document.metadata,
        },
    )


class ChildMemoryRetriever(BaseRetriever):
    """pgvector-backed retrieval for exactly one child."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    repository: RecommendationRepository
    child_id: str
    embedder: Embedder = Field(default_factory=HashingEmbedder)
    k: int = DEFAULT_K
    floor: float = DEFAULT_FLOOR

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        raise SyncRetrievalNotSupportedError(
            "ChildMemoryRetriever is async-only; use ainvoke() / aget_relevant_documents()."
        )

    async def _aget_relevant_documents(
        self, query: str, *, run_manager: AsyncCallbackManagerForRetrieverRun
    ) -> list[Document]:
        vector = self.embedder.embed(query)
        # Over-fetch, then apply the floor. Applying the floor in SQL would mean
        # the LIMIT and the threshold fight each other: a query whose top result
        # is weak would return nothing, when the honest answer is "here are the
        # two documents that did clear the bar".
        hits = await self.repository.search(self.child_id, vector, limit=self.k * 2)
        kept = [(doc, score) for doc, score in hits if score >= self.floor][: self.k]
        logger.info("memory_retrieved", child_id=self.child_id, count=len(kept))
        return [to_langchain(document, score) for document, score in kept]


class InMemoryChildMemoryRetriever(BaseRetriever):
    """The same interface over a list. Used by every test that has no database."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    documents: list[MemoryDocument] = Field(default_factory=list)
    embedder: Embedder = Field(default_factory=HashingEmbedder)
    k: int = DEFAULT_K
    floor: float = DEFAULT_FLOOR

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        return self._search(query)

    async def _aget_relevant_documents(
        self, query: str, *, run_manager: AsyncCallbackManagerForRetrieverRun
    ) -> list[Document]:
        return self._search(query)

    def _search(self, query: str) -> list[Document]:
        by_id = {document.doc_id: document for document in self.documents}
        corpus = [
            (document.doc_id, self.embedder.embed(document.text_ar))
            for document in self.documents
        ]
        ranked = top_k(self.embedder.embed(query), corpus, k=self.k, floor=self.floor)
        return [to_langchain(by_id[doc_id], score) for doc_id, score in ranked]


def as_payload(documents: Sequence[Document], *, limit: int = DEFAULT_K) -> list[dict[str, Any]]:
    """Retrieved documents as the plain JSON the gateway serialises.

    Only three keys cross into the prompt: what kind of record it is, when it
    happened, and what it says. The score does not -- a model told that one piece
    of evidence scored 0.71 and another 0.68 will reason about the numbers, and
    those numbers are an artefact of a hashing embedder, not a measurement of
    how much the evidence matters.
    """
    payload: list[dict[str, Any]] = []
    for document in documents[:limit]:
        payload.append(
            {
                "kind": str(document.metadata.get("kind", "note")),
                "at": str(document.metadata.get("at", "")),
                "text": document.page_content,
            }
        )
    return payload


def cited_ids(documents: Sequence[Document], *, limit: int = DEFAULT_K) -> list[str]:
    """Document ids, for the `grounded_in` audit trail."""
    return [str(document.metadata.get("doc_id", "")) for document in documents[:limit]]


__all__ = [
    "DEFAULT_FLOOR",
    "DEFAULT_K",
    "ChildMemoryRetriever",
    "InMemoryChildMemoryRetriever",
    "SyncRetrievalNotSupportedError",
    "as_payload",
    "cited_ids",
    "to_langchain",
]
