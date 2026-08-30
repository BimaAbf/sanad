"""Weighted phoneme similarity — the lenient half of the scorer.

The substitution-cost matrix is transcribed from docs/04d §3, and the reasoning
behind it is the whole point of this file:

    Emphatic↔plain, stopping, cluster reduction and final-consonant deletion are
    the *expected* developmental error patterns for this population. A metric
    that charges full price for them measures orofacial motor control, not word
    knowledge — and then tells a child who knew the word that they were wrong.

So those four classes are cheap, everything else is not, and the threshold on
top of them (0.55) sits deliberately on the permissive side.

Pure. No I/O.
"""

from __future__ import annotations

from app.modules.voice.domain.g2p import LONG_VOWELS, is_consonant

#: docs/04d §3.
COST_EMPHATIC = 0.2
COST_STOPPING = 0.3
COST_CLUSTER_REDUCTION = 0.3
COST_FINAL_DELETION = 0.3
COST_VOWEL_LENGTH = 0.15
COST_OTHER = 1.0
COST_INDEL = 0.8

#: Emphatic ↔ plain. ق/ك is in the list because Egyptian realises ق as a glottal
#: stop, so the "plain" partner a child produces is /ʔ/ (token "2") as often as
#: it is /k/. Both pairings are listed rather than picking one.
EMPHATIC_PAIRS: frozenset[frozenset[str]] = frozenset(
    {
        frozenset({"S", "s"}),
        frozenset({"T", "t"}),
        frozenset({"D", "d"}),
        frozenset({"Z", "z"}),
        frozenset({"q", "k"}),
        frozenset({"2", "k"}),
        frozenset({"q", "2"}),
    }
)

#: Fricative → stop ("stopping"), the most common phonological process here.
#: Directional in the literature, but the scorer must be symmetric: it does not
#: know which side of the pair the child produced, only that they differ.
STOPPING_PAIRS: frozenset[frozenset[str]] = frozenset(
    {
        frozenset({"s", "t"}),
        frozenset({"$", "t"}),
        frozenset({"z", "d"}),
        frozenset({"S", "T"}),
        frozenset({"f", "b"}),
        frozenset({"x", "k"}),
        frozenset({"G", "g"}),
        frozenset({"H", "h"}),
    }
)

VOWEL_LENGTH_PAIRS: frozenset[frozenset[str]] = frozenset(
    {frozenset({"a", "A"}), frozenset({"i", "I"}), frozenset({"u", "U"})}
)


def substitution_cost(expected: str, heard: str) -> float:
    """Cost of hearing `heard` where `expected` was expected."""
    if expected == heard:
        return 0.0
    pair = frozenset({expected, heard})
    if pair in EMPHATIC_PAIRS:
        return COST_EMPHATIC
    if pair in STOPPING_PAIRS:
        return COST_STOPPING
    if pair in VOWEL_LENGTH_PAIRS:
        return COST_VOWEL_LENGTH
    return COST_OTHER


def deletion_cost(expected: str, index: int, length: int, neighbours: tuple[str, str]) -> float:
    """Cost of the child omitting `expected[index]`.

    Four prices, in the order they are checked:

    * **vowel shortening** — a long vowel between two consonants. See below.
    * **final consonant deletion** — the last phoneme, and a consonant. Word
      identity survives (أحمر → أحم is still unmistakably أحمر).
    * **cluster reduction** — a consonant with a consonant neighbour. Dropping
      one of CC is near-universal and the target is still being attempted.
    * everything else — a plain indel.

    ================================================================================
    HOW docs/04d §3's `vowel length 0.15` IS ACTUALLY REACHED
    ================================================================================
    docs/04d §3 prices a vowel-length error at 0.15 and writes it as the pair
    `a/aː` — a *substitution*. Through this pipeline that substitution can never
    happen. Unvowelised Arabic writes no short vowels, ASR returns unvowelised
    text, and `normalize_ar` strips any tashkeel that survives, so `g2p` emits
    a short vowel in exactly two places (the definite article, and word-final
    ة) and never emits /i/ or /u/ at all.

    The only way a length contrast can present itself in this orthography is as
    the **presence or absence of the mater lectionis** — ا و ي. A child who
    shortens the vowel of /baːb/ produces something an unvowelised transcript
    writes as بب, so the scorer sees a DELETED long vowel. Pricing that as an
    ordinary indel charged 0.8 for the single error class the document calls
    "almost never meaningful" — 5.3× the intended price. Stacked with one other
    expected process it pushed a child out of the accept band: راس /rAs/ produced
    as /rt/ — the vowel shortened and the final /s/ stopped, two textbook
    processes — scored (0.8 + 0.3)/3 → 0.633, a `retry`, where the documented
    costs give (0.15 + 0.3)/3 → 0.850, an `accept`.

    **Between two consonants, and deletion only.** Both restrictions are load-
    bearing and both were established by running the 62-pair corpus:

    * *Between two consonants* is what vowel shortening looks like: CVC → CC,
      the syllable keeps its shape and loses its length. A long vowel deleted at
      a word edge changes the shape of the word and stays at 0.8.
    * *Deletion only.* An INSERTED long vowel — one in the recogniser's output
      that the target does not contain — is not a shortening; it is extra
      material. Pricing it cheaply lets the aligner slide two unrelated strings
      past each other almost for free, and it measurably does: with cheap
      insertions صابونة against ترابيزة rises from 0.457 to 0.557 and a
      genuine non-match crosses the accept threshold. Insertions stay at 0.8.

    The asymmetry is legitimate because the scorer knows which side is the
    target. Deleting a written long vowel says something about how the child
    produced a known word; inserting one says nothing about that word at all.

    **This rule has not been reviewed by a speech-language therapist**, for the
    same reason `is_a_different_taught_word` has not. → REVIEW-QUEUE.md #8
    ================================================================================
    """
    before, after = neighbours
    if expected in LONG_VOWELS:
        if before and after and is_consonant(before) and is_consonant(after):
            return COST_VOWEL_LENGTH
        return COST_INDEL
    if not is_consonant(expected):
        return COST_INDEL
    if index == length - 1:
        return COST_FINAL_DELETION
    if (before and is_consonant(before)) or (after and is_consonant(after)):
        return COST_CLUSTER_REDUCTION
    return COST_INDEL


def edit_cost(expected: str, heard: str) -> float:
    """Weighted Levenshtein distance, in cost units."""
    rows = len(expected)
    columns = len(heard)

    # Row 0: the child said nothing of the expected word. Charge the real
    # deletion price for each phoneme rather than a flat indel, so "said one
    # syllable of a long word" is not scored the same as "said nothing".
    previous: list[float] = [0.0]
    for index in range(rows):
        neighbours = (
            expected[index - 1] if index > 0 else "",
            expected[index + 1] if index + 1 < rows else "",
        )
        previous.append(previous[index] + deletion_cost(expected[index], index, rows, neighbours))

    # `previous` is indexed by expected-length; iterate heard along the columns.
    grid = [previous]
    for column in range(1, columns + 1):
        row = [grid[column - 1][0] + COST_INDEL]
        for index in range(1, rows + 1):
            neighbours = (
                expected[index - 2] if index > 1 else "",
                expected[index] if index < rows else "",
            )
            substitute = grid[column - 1][index - 1] + substitution_cost(
                expected[index - 1], heard[column - 1]
            )
            delete = row[index - 1] + deletion_cost(
                expected[index - 1], index - 1, rows, neighbours
            )
            # Flat, including for a long vowel. `deletion_cost` explains why the
            # vowel-length discount is deletion-only: a cheap vowel INSERTION
            # buys the aligner a free realignment and lets a genuine non-match
            # cross the accept threshold.
            insert = grid[column - 1][index] + COST_INDEL
            row.append(min(substitute, delete, insert))
        grid.append(row)

    return grid[columns][rows]


def phoneme_similarity(expected: str, heard: str) -> float:
    """1.0 for identical, 0.0 for nothing in common. Never outside [0, 1].

    Normalised by the longer of the two strings, not by the expected word. Using
    the expected length alone would let a hypothesis that is the target plus
    five phonemes of noise score as a perfect match, because the extra
    insertions would be divided away.
    """
    if not expected and not heard:
        return 1.0
    normaliser = max(len(expected), len(heard))
    if normaliser == 0:  # pragma: no cover - unreachable given the guard above
        return 1.0
    return max(0.0, min(1.0, 1.0 - edit_cost(expected, heard) / normaliser))
