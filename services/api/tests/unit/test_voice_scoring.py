"""T09 — the pronunciation scorer.

The corpus lives in `voice_corpus.py` with a linguistic rationale on every row.
This file is the harness plus the boundary, normalisation and provider tests.
"""

from __future__ import annotations

import pytest
from tests.unit.voice_corpus import CORPUS, Pair

from app.modules.voice.domain.g2p import g2p
from app.modules.voice.domain.normalize import normalize_ar, strip_tashkeel
from app.modules.voice.domain.scoring import (
    ACCEPT_THRESHOLD,
    RETRY_THRESHOLD,
    AsrResult,
    AttemptResult,
    ExpectedWord,
    Hypothesis,
    Verdict,
    caregiver_override,
    classify,
    score_attempt,
)
from app.modules.voice.domain.similarity import (
    COST_CLUSTER_REDUCTION,
    COST_EMPHATIC,
    COST_FINAL_DELETION,
    COST_INDEL,
    COST_OTHER,
    COST_STOPPING,
    COST_VOWEL_LENGTH,
    deletion_cost,
    edit_cost,
    phoneme_similarity,
    substitution_cost,
)

#: Every word the curriculum teaches, for the closed-set rule. Kept small and
#: explicit rather than imported from the seed, so a curriculum edit cannot
#: silently change what this suite is asserting.
TAUGHT_WORDS: tuple[str, ...] = (
    "أحمر",
    "أزرق",
    "أصفر",
    "أخضر",
    "باب",
    "شباك",
    "شوكة",
    "معلقة",
    "سكينة",
    "طبق",
    "كوباية",
    "كرسي",
    "ترابيزة",
    "سرير",
    "مخدة",
    "جزمة",
    "شنطة",
    "لبس",
    "مشط",
    "فرشة",
    "صابونة",
    "فوطة",
    "بطن",
    "راس",
    "شعر",
    "عين",
    "ودن",
    "مناخير",
    "بق",
    "سنان",
    "إيد",
    "رجل",
    "بابا",
    "ماما",
    "مية",
)


def _score(pair: Pair) -> tuple[Verdict, float]:
    expected = ExpectedWord(skill_code="t", label_ar=pair.expected, label_egy=pair.expected)
    competing = tuple(word for word in TAUGHT_WORDS if word != pair.expected)
    result = AsrResult(n_best=(Hypothesis(text=pair.heard, confidence=0.9),), provider="null")
    score = score_attempt(expected, result, attempt_no=1, competing_labels=competing)
    return score.verdict, score.similarity


@pytest.mark.parametrize("pair", CORPUS, ids=lambda p: f"{p.process}:{p.expected}->{p.heard}")
def test_corpus_produces_the_expected_verdict(pair: Pair) -> None:
    verdict, similarity = _score(pair)
    assert verdict.value == pair.verdict, (
        f"{pair.expected} heard as {pair.heard} "
        f"({g2p(pair.expected)} vs {g2p(pair.heard)}) scored {similarity:.3f} "
        f"-> {verdict.value}, expected {pair.verdict}. Rationale: {pair.rationale}"
    )


def test_corpus_covers_every_substitution_class() -> None:
    """A class with no row is a class whose cost nothing checks."""
    processes = {pair.process for pair in CORPUS}
    assert {
        "emphatic",
        "stopping",
        "cluster",
        "final_deletion",
        "vowel_shortening",
        "metathesis",
        "combined",
        "non_match",
    } <= processes


def test_corpus_has_sixty_pairs_and_ten_non_matches() -> None:
    """docs/09 P09: 60 pairs including 10 genuine non-matches."""
    assert len(CORPUS) >= 60
    assert len([pair for pair in CORPUS if pair.process == "non_match"]) == 10


def test_no_genuine_non_match_is_ever_accepted() -> None:
    """The one property in the corpus that is not a judgement call."""
    for pair in CORPUS:
        if pair.process != "non_match":
            continue
        verdict, similarity = _score(pair)
        assert verdict is not Verdict.ACCEPT, (
            f"{pair.expected} would be accepted when the child said {pair.heard} "
            f"(similarity {similarity:.3f})"
        )


# --- normalisation ---------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("الأَحْمَر", "الاحمر"),
        ("أحمر", "احمر"),
        ("إيد", "ايد"),
        ("آسف", "اسف"),
        ("صابونة", "صابونه"),
        ("مستشفى", "مستشفي"),
        ("كــــتاب", "كتاب"),
        ("  أحمر  ", "احمر"),
        ("أحمر، أزرق", "احمر ازرق"),
        ("٣", "3"),
    ],
)
def test_normalize_ar(raw: str, expected: str) -> None:
    assert normalize_ar(raw) == expected


def test_strip_tashkeel_leaves_letters_alone() -> None:
    assert strip_tashkeel("وَرِّيني") == "وريني"


def test_normalisation_is_idempotent() -> None:
    for pair in CORPUS:
        once = normalize_ar(pair.expected)
        assert normalize_ar(once) == once


def test_g2p_uses_egyptian_jeem() -> None:
    """docs/12 §3.5: جزمة is /gazma/, never /dʒazma/.

    The whole voice tier rejected a Saudi-dialect TTS over this. A regression
    here would teach a child a word their family does not use.
    """
    assert g2p("جزمة").startswith("g")
    assert g2p("جبنة").startswith("g")


def test_g2p_assimilates_the_definite_article() -> None:
    """Sun letter: الشمس is /a$$ams/, not /al$ams/."""
    assert g2p("الشمس").startswith("a$$")
    # Moon letter keeps the /l/.
    assert g2p("القمر").startswith("al")


def test_g2p_final_ta_marbuta_is_a_vowel_not_an_h() -> None:
    assert g2p("شوكة").endswith("a")


# --- the cost table --------------------------------------------------------


def test_substitution_costs_match_docs_04d() -> None:
    assert substitution_cost("S", "s") == COST_EMPHATIC
    assert substitution_cost("T", "t") == COST_EMPHATIC
    assert substitution_cost("$", "t") == COST_STOPPING
    assert substitution_cost("a", "A") == COST_VOWEL_LENGTH
    assert substitution_cost("b", "n") == COST_OTHER
    assert substitution_cost("b", "b") == 0.0


def test_vowel_length_cost_is_reachable_from_a_vowelised_phoneme_string() -> None:
    """The 0.15 class as docs/04d §3 writes it — a substitution.

    This is the form a reviewed, vowelised `phonemes` column would supply. It is
    not the form that reaches the scorer from Arabic text today; that path is
    the deletion tested below.
    """
    assert substitution_cost("a", "A") == COST_VOWEL_LENGTH
    assert edit_cost("bAb", "bab") == pytest.approx(COST_VOWEL_LENGTH)
    assert phoneme_similarity("bAb", "bab") == pytest.approx(1 - COST_VOWEL_LENGTH / 3)


def test_vowel_length_cost_is_reachable_from_unvowelised_arabic() -> None:
    """The path that actually exists, and the defect it fixes.

    Unvowelised Arabic writes no short vowels, so a child who shortens the vowel
    of /baːb/ is transcribed بب and the scorer sees a DELETED long vowel, not a
    substitution. That deletion used to be priced as an ordinary indel — 0.8 for
    the class docs/04d §3 calls "almost never meaningful".
    """
    assert deletion_cost("A", 1, 3, ("b", "b")) == COST_VOWEL_LENGTH
    assert phoneme_similarity(g2p("باب"), g2p("بب")) == pytest.approx(1 - COST_VOWEL_LENGTH / 3)

    # The consequence that made it worth fixing: two expected developmental
    # processes at once used to fall out of the accept band. راس /rAs/ produced
    # as /rt/ — shortened vowel plus stopping of the final /s/ — cost
    # (0.8 + 0.3)/3 -> 0.633, a `retry`. At the documented price it is
    # (0.15 + 0.3)/3 -> 0.850, an `accept`.
    stopping_plus_shortening = phoneme_similarity("rAs", "rt")
    assert stopping_plus_shortening == pytest.approx(0.85)
    assert stopping_plus_shortening >= ACCEPT_THRESHOLD


def test_the_vowel_length_discount_is_deletion_only_and_consonant_flanked() -> None:
    """Both restrictions, and the non-match that establishes the second.

    A cheap long-vowel INSERTION would let the aligner slide two unrelated
    strings together: صابونة against ترابيزة rises from 0.464 to 0.557 and
    crosses the accept threshold. Insertions therefore stay at 0.8.
    """
    # word-edge long vowels are not shortening, they change the word's shape
    assert deletion_cost("A", 0, 3, ("", "b")) == COST_INDEL
    assert deletion_cost("A", 2, 3, ("b", "")) == COST_INDEL
    # an inserted long vowel costs a full indel: bb -> bAb is 0.8, not 0.15
    assert edit_cost("bb", "bAb") == pytest.approx(COST_INDEL)
    # and the non-match it protects stays out of the accept band
    assert phoneme_similarity(g2p("صابونة"), g2p("ترابيزة")) < ACCEPT_THRESHOLD


def test_deletion_is_cheap_in_a_cluster_and_at_the_end() -> None:
    # r inside the fr$ cluster
    assert deletion_cost("r", 1, 4, ("f", "$")) == COST_CLUSTER_REDUCTION
    # final r of AHmr
    assert deletion_cost("r", 3, 4, ("m", "")) == COST_FINAL_DELETION
    # a short vowel is never a length error: it is an ordinary indel
    assert deletion_cost("a", 1, 3, ("b", "b")) == COST_INDEL


def test_similarity_is_bounded_and_symmetric_for_identical_input() -> None:
    assert phoneme_similarity("", "") == 1.0
    assert phoneme_similarity("bAb", "bAb") == 1.0
    assert 0.0 <= phoneme_similarity("bAb", "krsI") <= 1.0
    assert phoneme_similarity("bAb", "") < 1.0


def test_noise_scores_low_and_never_negative() -> None:
    """A long junk hypothesis must not be rescued by partial alignment.

    It does not score 0.0 — /s/ and /I/ do align somewhere in there — but
    normalising by the LONGER string keeps it far below the retry band, which is
    the property that matters. Normalising by the expected length instead would
    let a hypothesis of "the target plus noise" score as a perfect match.
    """
    similarity = phoneme_similarity("SAbUna", "krsIkrsIkrsI")
    assert 0.0 <= similarity < RETRY_THRESHOLD


# --- verdict bands ---------------------------------------------------------


def test_verdict_boundaries() -> None:
    """T09 §4: 0.54 -> retry, 0.56 -> accept, and the exact boundaries."""
    assert classify(0.56) is Verdict.ACCEPT
    assert classify(ACCEPT_THRESHOLD) is Verdict.ACCEPT
    assert classify(0.54) is Verdict.RETRY
    assert classify(RETRY_THRESHOLD) is Verdict.RETRY
    assert classify(0.2999) is Verdict.UNCLEAR
    assert classify(0.0) is Verdict.UNCLEAR


# --- accept on effort ------------------------------------------------------

WORD = ExpectedWord(skill_code="color_red", label_ar="أحمر", label_egy="أحمر")

#: Not audio — the *transcript* a recogniser returns when it is fed noise. This
#: is what "pure noise" looks like by the time it reaches the scorer.
NOISE_HYPOTHESES = (
    Hypothesis(text="زززز", confidence=0.02),
    Hypothesis(text="ككك", confidence=0.01),
)


def test_attempt_two_is_always_accepted_even_on_pure_noise() -> None:
    """docs/04d §3. The single most important behaviour in this module.

    After two attempts the answer is accepted whatever was heard, because a
    child who tried twice is not told they were wrong. Measurement stays honest
    through the `accepted_on_effort` result, which BKT discounts.
    """
    score = score_attempt(WORD, AsrResult(n_best=NOISE_HYPOTHESES), attempt_no=2)
    assert score.verdict is Verdict.ACCEPT
    assert score.result is AttemptResult.ACCEPTED_ON_EFFORT
    assert score.similarity < ACCEPT_THRESHOLD


def test_attempt_two_is_accepted_even_with_no_hypotheses_at_all() -> None:
    score = score_attempt(WORD, AsrResult(n_best=(), unavailable=True), attempt_no=2)
    assert score.verdict is Verdict.ACCEPT
    assert score.result is AttemptResult.ACCEPTED_ON_EFFORT


def test_attempt_two_that_is_actually_correct_records_correct_not_effort() -> None:
    score = score_attempt(WORD, AsrResult(n_best=(Hypothesis("أحمر"),)), attempt_no=2)
    assert score.result is AttemptResult.CORRECT
    assert score.matched_exactly


def test_attempt_one_noise_is_unclear_and_records_nothing() -> None:
    score = score_attempt(WORD, AsrResult(n_best=NOISE_HYPOTHESES), attempt_no=1)
    assert score.verdict is Verdict.UNCLEAR
    # No attempt row: the child has not finished answering.
    assert score.result is None


def test_retry_records_nothing_either() -> None:
    score = score_attempt(WORD, AsrResult(n_best=(Hypothesis("أزرق"),)), attempt_no=1)
    assert score.verdict is Verdict.RETRY
    assert score.result is None


def test_asr_unavailable_on_attempt_one_is_not_a_judgement() -> None:
    score = score_attempt(WORD, AsrResult(unavailable=True), attempt_no=1)
    assert score.verdict is Verdict.UNCLEAR
    assert score.reason == "asr_unavailable"
    assert score.similarity == 0.0
    assert score.result is None


def test_any_hypothesis_may_match_not_only_the_top_one() -> None:
    """n-best exists because the top hypothesis is a weak signal here."""
    result = AsrResult(
        n_best=(
            Hypothesis("كرسي", confidence=0.9),
            Hypothesis("مشط", confidence=0.5),
            Hypothesis("أحمر", confidence=0.1),
        )
    )
    score = score_attempt(WORD, result, attempt_no=1)
    assert score.verdict is Verdict.ACCEPT
    assert score.matched_exactly


def test_the_colloquial_form_matches_as_well_as_the_written_one() -> None:
    word = ExpectedWord(skill_code="num_2", label_ar="٢", label_egy="اتنين")
    score = score_attempt(word, AsrResult(n_best=(Hypothesis("اتنين"),)), attempt_no=1)
    assert score.matched_exactly


def test_a_reviewed_phoneme_column_supersedes_g2p() -> None:
    word = ExpectedWord(skill_code="color_red", label_ar="أحمر", label_egy="أحمر", phonemes="aHmar")
    assert word.phoneme_targets() == ("aHmar",)


def test_placeholder_phonemes_are_ignored() -> None:
    """seeds/curriculum.py ships `PLACEHOLDER:<code>`; it must never be scored."""
    word = ExpectedWord(
        skill_code="color_red",
        label_ar="أحمر",
        label_egy="أحمر",
        phonemes="PLACEHOLDER-NOT-REVIEWED:color_red",
    )
    assert word.phoneme_targets() == (g2p("أحمر"),)


def test_competing_word_rule_only_lowers_never_raises() -> None:
    """A hypothesis that is a different taught word cannot be accepted...

    ...but a hypothesis that scores `unclear` is not promoted to `retry` by it.
    """
    door = ExpectedWord(skill_code="hh_door", label_ar="باب", label_egy="باب")
    capped = score_attempt(
        door, AsrResult(n_best=(Hypothesis("شباك"),)), attempt_no=1, competing_labels=("شباك",)
    )
    assert capped.verdict is Verdict.RETRY
    assert "competing_taught_word" in capped.guardrail_notes

    unrelated = score_attempt(
        door, AsrResult(n_best=(Hypothesis("كرسي"),)), attempt_no=1, competing_labels=("كرسي",)
    )
    assert unrelated.verdict is Verdict.UNCLEAR


def test_competing_word_rule_never_blocks_the_target_itself() -> None:
    score = score_attempt(
        WORD, AsrResult(n_best=(Hypothesis("أحمر"),)), attempt_no=1, competing_labels=("أحمر",)
    )
    assert score.verdict is Verdict.ACCEPT


def test_caregiver_override_is_a_full_accept() -> None:
    score = caregiver_override()
    assert score.verdict is Verdict.ACCEPT
    assert score.result is AttemptResult.CAREGIVER_CONFIRMED
    assert score.similarity == 1.0


def test_an_empty_hypothesis_is_not_a_competing_word() -> None:
    """A recogniser that heard nothing has not heard a different word."""
    from app.modules.voice.domain.scoring import is_a_different_taught_word

    assert not is_a_different_taught_word("", ("شباك",))
    assert not is_a_different_taught_word("   ", ("شباك",))
    assert is_a_different_taught_word("شباك", ("شباك",))


def test_a_worse_later_hypothesis_does_not_replace_a_better_one() -> None:
    """n-best is ordered by the provider's confidence, not by our similarity."""
    result = AsrResult(
        n_best=(Hypothesis("أحم", confidence=0.9), Hypothesis("كرسي", confidence=0.4))
    )
    score = score_attempt(WORD, result, attempt_no=1)
    assert score.heard == "أحم"
    assert score.verdict is Verdict.ACCEPT


def test_g2p_of_an_empty_string_is_empty() -> None:
    from app.modules.voice.domain.g2p import _phonemise_word

    assert g2p("") == ""
    assert _phonemise_word("") == ""
