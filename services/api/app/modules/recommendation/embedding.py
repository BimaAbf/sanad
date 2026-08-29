"""Embeddings for the retrieval index.

================================================================================
WHY THIS IS NOT A VENDOR CALL, STATED PLAINLY
================================================================================
There is no embedding provider in this stack. docs/12 routes the whole product
to Groq, and Groq's OpenAI-compatible surface serves chat completions, audio
transcriptions and a preview TTS -- it has no `/embeddings` endpoint. Anthropic
has never had one. Adding a third vendor (Voyage, Cohere) for this one job would
mean a new key, a new DPA to read before any pilot traffic -- docs/12 §2.4 is
unambiguous that this is child health-adjacent data in a PDPL jurisdiction --
and a retrieval path that cannot run in CI or offline, in a codebase whose
central design property is that everything works with no key present.

So the default embedder is written here: signed feature hashing over Arabic
character n-grams. It is a real vector space -- 256 dense dimensions, cosine
similarity, a real pgvector index -- and it is genuinely weaker than a learned
model. What it captures is lexical and morphological overlap, which is most of
what this corpus needs: the documents being retrieved are short, highly
templated Arabic sentences about a fixed 88-skill curriculum, where the useful
signal is "this is about colours" and "this mentions the word red", not
paraphrase.

What it does NOT capture, so that nobody discovers it the hard way: synonymy
across different roots, and MSA/Egyptian pairs that share no letters. A
caregiver asking about the colours retrieves colour documents; one asking with a
synonym that shares no letters with the curriculum label will not.

`Embedder` is a protocol and `EMBEDDING_DIM` is read by the migration, so
swapping in a learned model later is a new class, a migration for the column
width, and a re-index -- not a rewrite. -> REVIEW-QUEUE.md

Pure. No I/O, no network, deterministic across processes and machines.
================================================================================
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Protocol, runtime_checkable

from app.modules.voice.domain.normalize import normalize_ar

#: Must equal the `vector(N)` width in migration 0009. A mismatch is an insert
#: that fails at runtime, which is why the migration imports this name rather
#: than repeating the number.
EMBEDDING_DIM = 256

#: Character n-gram width. 3 is the usual choice for Arabic retrieval: 2 is
#: dominated by the definite article, and 4 stops matching across a single
#: inflected letter, which is most of what varies between the forms of a label.
NGRAM = 3

#: Word-boundary marker, so three letters at the start of a word are a different
#: feature from the same three letters mid-word.
BOUNDARY = "⠂"

_WORD_RE = re.compile(r"[^\s]+")


@runtime_checkable
class Embedder(Protocol):
    """The seam a learned model would slot into."""

    name: str
    dim: int

    def embed(self, text: str) -> list[float]: ...

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]: ...


def tokens(text: str) -> list[str]:
    """Word unigrams plus character n-grams, over the normalised form.

    Both, not one or the other. Unigrams give exact-label matches their full
    weight -- a curriculum label appearing as a whole word is the strongest
    evidence a document is about that skill -- and the n-grams are what let an
    inflected or mis-spelled form still land near it.
    """
    normalised = normalize_ar(text)
    if not normalised:
        return []
    out: list[str] = []
    for word in _WORD_RE.findall(normalised):
        out.append(f"w:{word}")
        padded = f"{BOUNDARY}{word}{BOUNDARY}"
        if len(padded) <= NGRAM:
            out.append(f"g:{padded}")
            continue
        out.extend(f"g:{padded[i : i + NGRAM]}" for i in range(len(padded) - NGRAM + 1))
    return out


def _bucket(token: str, dim: int) -> tuple[int, float]:
    """(index, sign) for one feature.

    blake2b rather than the builtin `hash()`. Python salts `hash()` per process,
    so an index built by the ingest worker would not be searchable by the API
    process -- a failure that presents as "retrieval returns nothing relevant"
    rather than as an error, and that would survive every test running in one
    process.

    The sign is the collision defence: two tokens landing in the same bucket
    cancel half the time instead of always reinforcing.
    """
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    return value % dim, 1.0 if (value >> 63) & 1 else -1.0


def l2_normalise(vector: list[float]) -> list[float]:
    """Unit length, so cosine distance in pgvector is a dot product.

    An all-zero vector stays all-zero rather than becoming NaN. That happens for
    a document with no indexable content at all, and it must degrade to
    "matches nothing" rather than to a row that poisons every search.
    """
    norm = math.sqrt(sum(component * component for component in vector))
    if norm == 0.0:
        return vector
    return [component / norm for component in vector]


class HashingEmbedder:
    """Signed feature hashing with sublinear term weighting."""

    name = "hashing-ar-v1"

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        if dim <= 0:
            raise ValueError("embedding dimension must be positive")
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        counts = Counter(tokens(text))
        for token, count in counts.items():
            index, sign = _bucket(token, self.dim)
            # 1 + log(tf). A label repeated nine times in a summary is more
            # about that label than one mentioned once, but not nine times more.
            vector[index] += sign * (1.0 + math.log(count))
        return l2_normalise(vector)

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosine similarity. Used by the in-memory fallback and by the tests.

    pgvector does this in the database on the real path; this exists so the
    retrieval logic is testable without one, and so a deployment whose `vector`
    extension is missing still answers instead of failing.
    """
    if len(left) != len(right):
        raise ValueError(f"dimension mismatch: {len(left)} vs {len(right)}")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def top_k(
    query: Sequence[float],
    corpus: Iterable[tuple[str, Sequence[float]]],
    *,
    k: int = 8,
    floor: float = 0.0,
) -> list[tuple[str, float]]:
    """The in-memory search. Ties break on the id, so the order is stable."""
    scored = [(identifier, cosine(query, vector)) for identifier, vector in corpus]
    ranked = sorted(
        (pair for pair in scored if pair[1] >= floor),
        key=lambda pair: (-pair[1], pair[0]),
    )
    return ranked[:k]


__all__ = [
    "EMBEDDING_DIM",
    "Embedder",
    "HashingEmbedder",
    "cosine",
    "l2_normalise",
    "tokens",
    "top_k",
]
