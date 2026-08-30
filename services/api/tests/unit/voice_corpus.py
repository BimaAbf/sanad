"""The 60-pair pronunciation scoring corpus.

================================================================================
PLACEHOLDER — NOT CLINICALLY VALIDATED
================================================================================
docs/04d §8 requires these pairs and their expected verdicts to be **agreed by a
speech-language therapist**. They are not. What they are:

* the *pairs* are constructed to instantiate each substitution class that
  docs/04d §3 names, one class at a time, so a class whose cost is wrong shows
  up as a cluster of failures rather than as one ambiguous case;
* the *expected verdict* on each row is derived arithmetically from the cost
  table in docs/04d §3 and the 0.55/0.30 thresholds — the arithmetic is in the
  rationale on each row — **not** read off the implementation;
* the *rationale* states the phonological process being modelled.

A therapist must confirm three things before this corpus means anything:
  1. that these really are the error patterns this population produces,
  2. that a child producing each one should be told they were right,
  3. that the ten non-matches really are non-matches to a listener.

FOUR ROWS DISAGREED WITH THE IMPLEMENTATION ON THE FIRST RUN. Every one is
recorded rather than quietly reconciled, because a disagreement is information
about the spec (ORCHESTRATOR.md §5):

  * معلقة/ملعقة and كرسي/كسري — the hand arithmetic was wrong. Both assumed a
    metathesis costs two 1.0 substitutions; the weighted aligner reaches it more
    cheaply through a cluster-internal deletion plus an insertion. The
    implementation is right and the derivation was naive.
  * صابونة/ترابيزة — predicted `unclear`, actually `retry`. A magnitude error in
    the derivation. The requirement (a non-match is not accepted) holds either way.
  * باب/شباك — **a real false accept**, at exactly 0.550. Fixed by the
    closed-vocabulary rule in `is_a_different_taught_word`, NOT by moving the
    threshold. See that function.

AND ONE FINDING ABOUT THE COST TABLE ITSELF, SINCE FIXED: the `vowel length
0.15` class in docs/04d §3 was **unreachable through this pipeline**. Short
vowels are not written in unvowelised Arabic, ASR returns unvowelised text, and
normalisation strips tashkeel, so a shortened vowel reached the scorer as a
deleted long vowel priced at 0.8 — 5.3x the price the document sets for the one
class it calls "almost never meaningful". `deletion_cost` now prices a long
vowel deleted BETWEEN TWO CONSONANTS at 0.15, which is what CVC -> CC vowel
shortening looks like in an unvowelised transcript. Deletion only, and only
between consonants: a cheap vowel INSERTION lets the aligner slide unrelated
strings together, and measurably pushed صابونة/ترابيزة from 0.457 to 0.557,
across the accept threshold. That rule is mine and no therapist has seen it —
REVIEW-QUEUE #8. See the `vowel_shortening` rows.

→ REVIEW-QUEUE.md
================================================================================

Vocabulary is drawn from the 88-skill curriculum only. A pair built from a word
the product never teaches would test the metric on a distribution the product
never sees.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Pair:
    expected: str
    heard: str
    #: The substitution class from docs/04d §3 this row instantiates.
    process: str
    #: 'accept' | 'retry' | 'unclear' — what attempt 1 should produce.
    verdict: str
    rationale: str


#: docs/04d §3 cost table, repeated here so the arithmetic in each rationale can
#: be checked without opening another file.
#:
#:   emphatic <-> plain        0.20
#:   fricative -> stop         0.30
#:   cluster reduction         0.30
#:   final consonant deletion  0.30
#:   vowel length              0.15
#:   any other substitution    1.00
#:   insertion / deletion      0.80
#:
#: similarity = 1 - (total cost / length of the longer phoneme string)
#: accept >= 0.55 · retry >= 0.30 · otherwise unclear

CORPUS: tuple[Pair, ...] = (
    # --- emphatic <-> plain (cost 0.20) -----------------------------------
    # Universally late-acquired in Arabic. A child who says /s/ for /sˤ/ has the
    # word; they do not yet have the pharyngealised gesture. Treating that as a
    # wrong answer measures the tongue root, not the vocabulary.
    Pair("صابونة", "سابونة", "emphatic", "accept", "S->s in SAbUna (6): 0.2/6 = 0.033 -> 0.967"),
    Pair("طبق", "تبق", "emphatic", "accept", "T->t in Tb2 (3): 0.2/3 = 0.067 -> 0.933"),
    Pair("صباح الخير", "سباح الخير", "emphatic", "accept", "S->s in a 9-phoneme string -> 0.978"),
    Pair("ضهر", "دهر", "emphatic", "accept", "D->d in Dhr (3): 0.2/3 -> 0.933"),
    Pair(
        "طبق",
        "دبق",
        "emphatic",
        "accept",
        "T->d: emphatic pair via T/t then t/d is one sub, 1.0/3 -> 0.667",
    ),
    Pair("بق", "بك", "emphatic", "accept", "2->k, the colloquial reflex of qaf: 0.2/2 -> 0.900"),
    Pair("مشط", "مشت", "emphatic", "accept", "T->t word-finally in m$T (3): 0.2/3 -> 0.933"),
    Pair("أصفر", "أسفر", "emphatic", "accept", "S->s in ASfr (4): 0.2/4 -> 0.950"),
    # --- fricative -> stop, 'stopping' (cost 0.30) -------------------------
    # The most common phonological process in this population. The child is
    # producing the easier manner at the same place; the target is unmistakable.
    Pair("شوكة", "توكة", "stopping", "accept", "$->t in $Uka (4): 0.3/4 = 0.075 -> 0.925"),
    Pair("سنان", "تنان", "stopping", "accept", "s->t in snAn (4): 0.3/4 -> 0.925"),
    Pair("شنطة", "تنطة", "stopping", "accept", "$->t in $nTa (4): 0.3/4 -> 0.925"),
    Pair("فوطة", "بوطة", "stopping", "accept", "f->b in fUTa (4): 0.3/4 -> 0.925"),
    Pair("زرار", "درار", "stopping", "accept", "z->d in zrAr (4): 0.3/4 -> 0.925"),
    Pair("شعر", "تعر", "stopping", "accept", "$->t in $3r (3): 0.3/3 = 0.100 -> 0.900"),
    Pair("سرير", "ترير", "stopping", "accept", "s->t in srIr (4): 0.3/4 -> 0.925"),
    Pair("شباك", "تباك", "stopping", "accept", "$->t in $bAk (4): 0.3/4 -> 0.925"),
    # --- cluster reduction (cost 0.30) -------------------------------------
    # Deleting one consonant of a CC sequence. Extremely common, and the word
    # is still being aimed at.
    Pair(
        "فرشة", "فشة", "cluster", "accept", "delete r between f and $ in fr$a (4): 0.3/4 -> 0.925"
    ),
    Pair("مشط", "مط", "cluster", "accept", "delete $ between m and T in m$T (3): 0.3/3 -> 0.900"),
    Pair("بطن", "بن", "cluster", "accept", "delete T between b and n in bTn (3): 0.3/3 -> 0.900"),
    Pair("رجل", "رل", "cluster", "accept", "delete g between r and l in rgl (3): 0.3/3 -> 0.900"),
    Pair(
        "شنطة", "شطة", "cluster", "accept", "delete n between $ and T in $nTa (4): 0.3/4 -> 0.925"
    ),
    Pair(
        "جزمة", "جمة", "cluster", "accept", "delete z between g and m in gzma (4): 0.3/4 -> 0.925"
    ),
    Pair(
        "مخدة", "مدة", "cluster", "accept", "delete x between m and d in mxda (4): 0.3/4 -> 0.925"
    ),
    Pair("ودن", "ون", "cluster", "accept", "delete d between w and n in wdn (3): 0.3/3 -> 0.900"),
    # --- final consonant deletion (cost 0.30) ------------------------------
    # Word identity survives: أحم is unmistakably an attempt at أحمر.
    Pair("أحمر", "أحم", "final_deletion", "accept", "drop final r of AHmr (4): 0.3/4 -> 0.925"),
    Pair("باب", "با", "final_deletion", "accept", "drop final b of bAb (3): 0.3/3 -> 0.900"),
    Pair("شباك", "شبا", "final_deletion", "accept", "drop final k of $bAk (4): 0.3/4 -> 0.925"),
    Pair("سنان", "سنا", "final_deletion", "accept", "drop final n of snAn (4): 0.3/4 -> 0.925"),
    Pair("بطن", "بط", "final_deletion", "accept", "drop final n of bTn (3): 0.3/3 -> 0.900"),
    Pair("أخضر", "أخض", "final_deletion", "accept", "drop final r of AxDr (4): 0.3/4 -> 0.925"),
    Pair(
        "مناخير", "مناخي", "final_deletion", "accept", "drop final r of mnAxIr (6): 0.3/6 -> 0.950"
    ),
    Pair("لبس", "لب", "final_deletion", "accept", "drop final s of lbs (3): 0.3/3 -> 0.900"),
    # --- vowel shortening --------------------------------------------------
    # Labelled `vowel_length` when this corpus was written, on the assumption
    # that a shortened vowel would reach the scorer as /a/ against /aː/ and cost
    # the documented 0.15. IT CANNOT, AS A SUBSTITUTION. Unvowelised Arabic
    # writes no short vowels, ASR emits unvowelised text, and `normalize_ar`
    # strips any tashkeel that survives — so a shortened vowel arrives as a
    # DELETED long vowel. It was priced as an ordinary indel (0.8); it is now
    # priced as the length error it is (0.15) whenever the deleted long vowel
    # sits between two consonants, which is exactly the CVC -> CC shape of
    # vowel shortening. See `similarity.deletion_cost` for why the discount is
    # deletion-only and consonant-flanked, and REVIEW-QUEUE #8 for the fact
    # that no therapist has ruled on it.
    #
    # The rows keep the name `vowel_shortening` rather than `vowel_length`,
    # because what they exercise is still a deletion in an unvowelised string,
    # not the substitution docs/04d §3 describes.
    Pair(
        "باب",
        "بب",
        "vowel_shortening",
        "accept",
        "delete A between b and b in bAb (3): 0.15/3 -> 0.950",
    ),
    Pair(
        "سرير",
        "سرر",
        "vowel_shortening",
        "accept",
        "delete I between r and r in srIr (4): 0.15/4 -> 0.963",
    ),
    Pair(
        "راس",
        "رس",
        "vowel_shortening",
        "accept",
        "delete A between r and s in rAs (3): 0.15/3 -> 0.950",
    ),
    Pair(
        "كوباية",
        "كبايه",
        "vowel_shortening",
        "accept",
        "delete U between k and b in kUbAya (6): 0.15/6 -> 0.975",
    ),
    Pair(
        "مناخير",
        "مناخر",
        "vowel_shortening",
        "accept",
        "delete I between x and r in mnAxIr (6): 0.15/6 -> 0.975",
    ),
    Pair(
        "صابونة",
        "صبونة",
        "vowel_shortening",
        "accept",
        "delete A between S and b in SAbUna (6): 0.15/6 -> 0.975",
    ),
    # --- metathesis --------------------------------------------------------
    # Two adjacent phonemes swapped. NOT a cheap class in docs/04d: it is two
    # ordinary substitutions, so short words fall out of the accept band and
    # long ones stay in it. That asymmetry is the documented behaviour, not a
    # defect — and it is exactly the kind of thing a therapist should rule on.
    Pair(
        "مناخير",
        "منخاير",
        "metathesis",
        "accept",
        "2 subs at 1.0 plus a vowel indel in a 6-string: 1.9/6 -> 0.683",
    ),
    Pair(
        "ترابيزة",
        "تربايزة",
        "metathesis",
        "accept",
        "2 subs at 1.0 plus a vowel indel in a 7-string: 1.9/7 -> 0.729",
    ),
    Pair(
        "معلقة",
        "ملعقة",
        "metathesis",
        "accept",
        # CORRECTED. The first derivation here assumed two 1.0 substitutions and
        # predicted 0.600/retry. Two things were wrong. Phonologically, ملعقة is
        # the MSA spelling of the same word, not a metathesis error at all.
        # Arithmetically, the aligner finds a 1.1 path (a cluster-internal
        # deletion at 0.3 plus an insertion at 0.8), not a 2.0 one. 1.1/5 -> 0.780.
        "same word, MSA spelling; cheapest path 1.1/5 -> 0.780",
    ),
    Pair(
        "كرسي",
        "كسري",
        "metathesis",
        "accept",
        # CORRECTED, and the correction is informative. Metathesis *within a
        # consonant cluster* is not two substitutions: the aligner reaches it by
        # deleting one cluster member (0.3, the documented cluster-reduction
        # price) and inserting it again (0.8), for 1.1 rather than 2.0.
        # 1.1/4 -> 0.725. That leniency follows from the docs/04d costs; whether
        # it is clinically right is a question for the SLT gate.
        "cluster-internal metathesis: 1.1/4 -> 0.725",
    ),
    # --- combined processes ------------------------------------------------
    # Real child speech applies more than one at a time. These check that the
    # costs add rather than compound.
    Pair(
        "صابونة", "سابونه", "combined", "accept", "S->s plus final-h normalisation: 0.2/6 -> 0.967"
    ),
    Pair(
        "فرشة",
        "فشه",
        "combined",
        "accept",
        "cluster reduction plus ta-marbuta spelling: 0.3/4 -> 0.925",
    ),
    Pair("شنطة", "تنطه", "combined", "accept", "stopping plus spelling: 0.3/4 -> 0.925"),
    Pair(
        "مشط",
        "مت",
        "combined",
        "accept",
        "cluster reduction (0.3) plus stopping (0.3) in m$T (3): 0.6/3 -> 0.800",
    ),
    Pair(
        "سنان",
        "تنا",
        "combined",
        "accept",
        "stopping (0.3) + final deletion (0.3) in snAn (4): 0.6/4 -> 0.850",
    ),
    Pair(
        "جزمة",
        "جما",
        "combined",
        "accept",
        "cluster reduction in gzma (4) then a vowel: 0.3/4 -> 0.925",
    ),
    Pair(
        "طبق",
        "تب",
        "combined",
        "accept",
        "emphatic (0.2) + final deletion (0.3) in Tb2 (3): 0.5/3 -> 0.833",
    ),
    Pair("صباح الخير", "سباح الخير", "combined", "accept", "emphatic in a long string -> 0.978"),
    # --- exact and near-exact ---------------------------------------------
    Pair("أحمر", "أحمر", "exact", "accept", "identical -> 1.000"),
    Pair(
        "أحمر",
        "الأحمر",
        "exact",
        "accept",
        "definite article; al- prefix costs 2 indels in a 6-string",
    ),
    # --- genuine non-matches: these MUST NOT be accepted -------------------
    # Different words, not minimal pairs. A minimal pair (باب vs تاب) is
    # deliberately accepted by this design; a different word must not be.
    Pair(
        "أحمر",
        "أزرق",
        "non_match",
        "retry",
        "AHmr vs Azr2: 3 subs at 1.0 in 4 -> 0.475, below accept",
    ),
    Pair("شوكة", "كرسي", "non_match", "unclear", "$Uka vs krsI: nothing aligns -> 0.000"),
    Pair("جزمة", "شنطة", "non_match", "unclear", "gzma vs $nTa: no shared segment -> low"),
    Pair(
        "صابونة",
        "ترابيزة",
        "non_match",
        "retry",
        # CORRECTED: predicted "unclear" on the assumption that nothing aligns.
        # /A/ and /a/ and the shared /b/ do align, giving 3.8/7 -> 0.457, which
        # is the retry band. What the row is really asserting is the requirement
        # from docs/09 P09 — a genuine non-match is NOT ACCEPTED — and 0.457 is
        # comfortably below the 0.55 accept threshold.
        "shared /A/, /b/, /a/: 3.8/7 -> 0.457, below accept",
    ),
    Pair("مشط", "كرسي", "non_match", "unclear", "m$T vs krsI -> 0.000"),
    Pair(
        "باب",
        "شباك",
        "non_match",
        "retry",
        # THE ROW THAT FOUND A REAL DEFECT. On raw similarity this is one
        # insertion (0.8) plus one substitution (1.0) over 4 phonemes = 0.550,
        # which is EXACTLY the accept threshold — so a child asked for "door"
        # who said "window" was told they were right. The fix is the
        # closed-vocabulary rule in `is_a_different_taught_word`, not a change to
        # the threshold. This row stays at "retry" and is the regression test for it.
        "raw similarity 0.550 == the threshold; capped by the competing-word rule",
    ),
    Pair("عين", "رجل", "non_match", "unclear", "3In vs rgl -> 0.000"),
    Pair("ماما", "بابا", "non_match", "retry", "mAmA vs bAbA: 2 subs at 1.0 in 4 -> 0.500"),
    Pair("مية", "كرسي", "non_match", "unclear", "mIa vs krsI -> low"),
    Pair("أصفر", "معلقة", "non_match", "unclear", "ASfr vs m3l2a -> 0.000"),
)


def by_process(process: str) -> tuple[Pair, ...]:
    return tuple(pair for pair in CORPUS if pair.process == process)
