"""The 88-skill curriculum.

================================================================================
REVIEWED-BY:
================================================================================
^^ That header is EMPTY and CI fails while it stays empty (P06 requires it).
It must carry the name of a native Egyptian Arabic speaker who has reviewed
every label in this file.

What is transcribed vs. what is invented:

  TRANSCRIBED from docs/02-data-model.md §10.1 — the architecture package is
  authoritative for these, and they are reproduced verbatim:
      * the 10 colour words        * the 10 body parts
      * the 20 household objects   * the 10 social phrases
      * the 28 letters and the ten numerals

  PLACEHOLDER — generated mechanically, NOT reviewed, NOT correct:
      * label_vowelised   (tashkeel) — drives TTS. Wrong tashkeel means Nour
                          mispronounces a word to a child learning to speak.
      * phonemes          (IPA) — drives the pronunciation similarity scorer.
      * transliteration
      * label_egy         where it differs from MSA
      * every distractor pool

A wrong vowelisation is not cosmetic here. The whole product is a child hearing
a word said correctly, repeatedly. → REVIEW-QUEUE.md #6
================================================================================
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Set to a reviewer's name to satisfy the CI check. Must not be a placeholder.
REVIEWED_BY: str = ""

PLACEHOLDER = "PLACEHOLDER-NOT-REVIEWED"

MIN_DISTRACTORS = 4


@dataclass(frozen=True, slots=True)
class Skill:
    code: str
    category: str
    label_ar: str
    label_vowelised: str
    label_egy: str
    transliteration: str
    phonemes: str
    difficulty_tier: int
    intro_order: int
    alt_text_ar: str
    #: Perceptual colour, as (L, a, b)-ish coordinates normalised to 0-1, used
    #: by the tier-1 contrast rule. None for non-colour skills.
    colour: tuple[float, float, float] | None = None
    distractor_pool: tuple[str, ...] = field(default_factory=tuple)
    prerequisites: tuple[str, ...] = field(default_factory=tuple)


# --- transcribed from docs/02 §10.1 ----------------------------------------

LETTERS: tuple[tuple[str, str], ...] = (
    ("alef", "أ"),
    ("baa", "ب"),
    ("taa", "ت"),
    ("thaa", "ث"),
    ("jeem", "ج"),
    ("haa", "ح"),
    ("khaa", "خ"),
    ("dal", "د"),
    ("thal", "ذ"),
    ("raa", "ر"),
    ("zay", "ز"),
    ("seen", "س"),
    ("sheen", "ش"),
    ("sad", "ص"),
    ("dad", "ض"),
    ("tah", "ط"),
    ("zah", "ظ"),
    ("ain", "ع"),
    ("ghain", "غ"),
    ("faa", "ف"),
    ("qaf", "ق"),
    ("kaf", "ك"),
    ("lam", "ل"),
    ("meem", "م"),
    ("noon", "ن"),
    ("haa2", "ه"),
    ("waw", "و"),
    ("yaa", "ي"),
)

#: Keyword words, per docs/02 §10.1 ("أ → أَسَد, ب → بَطَّة, ت → تُفَّاحة …").
#: Only the three the document actually gives are real; the rest are
#: PLACEHOLDERS and are marked as such.
LETTER_KEYWORDS: dict[str, str] = {
    "alef": "أسد",
    "baa": "بطة",
    "taa": "تفاحة",
}

NUMERALS: tuple[tuple[str, str, str], ...] = (
    ("1", "١", "واحد"),
    ("2", "٢", "اتنين"),
    ("3", "٣", "تلاتة"),
    ("4", "٤", "أربعة"),
    ("5", "٥", "خمسة"),
    ("6", "٦", "ستة"),
    ("7", "٧", "سبعة"),
    ("8", "٨", "تمانية"),
    ("9", "٩", "تسعة"),
    ("10", "١٠", "عشرة"),
)

#: (code suffix, label, approximate perceptual coordinates).
#: The coordinates are a PLACEHOLDER stand-in for real CIELAB values; they exist
#: so the tier-1 contrast rule has something to compute on.
COLOURS: tuple[tuple[str, str, tuple[float, float, float]], ...] = (
    ("red", "أحمر", (0.53, 0.90, 0.75)),
    ("blue", "أزرق", (0.42, 0.30, 0.10)),
    ("yellow", "أصفر", (0.86, 0.55, 0.95)),
    ("green", "أخضر", (0.55, 0.15, 0.75)),
    ("white", "أبيض", (1.00, 0.50, 0.50)),
    ("black", "أسود", (0.00, 0.50, 0.50)),
    ("orange", "برتقالي", (0.65, 0.78, 0.88)),
    ("brown", "بني", (0.40, 0.62, 0.68)),
    ("pink", "وردي", (0.75, 0.80, 0.55)),
    ("purple", "بنفسجي", (0.45, 0.68, 0.25)),
)

BODY_PARTS: tuple[tuple[str, str], ...] = (
    ("head", "راس"),
    ("hair", "شعر"),
    ("eye", "عين"),
    ("ear", "ودن"),
    ("nose", "مناخير"),
    ("mouth", "بق"),
    ("teeth", "سنان"),
    ("hand", "إيد"),
    ("leg", "رجل"),
    ("tummy", "بطن"),
)

HOUSEHOLD: tuple[tuple[str, str], ...] = (
    ("toothbrush", "فرشة سنان"),
    ("toothpaste", "معجون"),
    ("soap", "صابونة"),
    ("towel", "فوطة"),
    ("fork", "شوكة"),
    ("spoon", "معلقة"),
    ("knife", "سكينة"),
    ("plate", "طبق"),
    ("cup", "كوباية"),
    ("water_glass", "كوباية مية"),
    ("chair", "كرسي"),
    ("table", "ترابيزة"),
    ("bed", "سرير"),
    ("pillow", "مخدة"),
    ("door", "باب"),
    ("window", "شباك"),
    ("shoes", "جزمة"),
    ("bag", "شنطة"),
    ("clothes", "لبس"),
    ("comb", "مشط"),
)

SOCIAL: tuple[tuple[str, str], ...] = (
    ("good_morning", "صباح الخير"),
    ("goodbye", "مع السلامة"),
    ("thanks", "شكرا"),
    ("please", "من فضلك"),
    ("yes", "أيوه"),
    ("no", "لأ"),
    ("come", "تعالى"),
    ("dad", "بابا"),
    ("mum", "ماما"),
    ("my_name", "اسمي"),
)


def _placeholder_vowelised(label: str) -> str:
    """A stand-in for real tashkeel.

    Deliberately returns the bare label rather than guessing diacritics: a wrong
    vowelisation would be silently *worse* than none, because it would be
    plausible enough to ship and would make Nour mispronounce the word.
    """
    return label


def _placeholder_phonemes(code: str) -> str:
    return f"{PLACEHOLDER}:{code}"


def _tier_for(category: str, index: int) -> int:
    """Introduction difficulty, 1-5. A mechanical placeholder ordering."""
    if category in ("colors", "body_parts"):
        return 1 if index < 5 else 2
    if category == "household":
        return 2 if index < 10 else 3
    if category == "social":
        return 1 if index < 4 else 2
    if category == "numbers":
        return 2 if index < 5 else 3
    return 3 if index < 14 else 4  # letters


def build_skills() -> list[Skill]:
    """All 88 skills, in introduction order. Deterministic."""
    skills: list[Skill] = []
    order = 0

    def add(
        code: str,
        category: str,
        label: str,
        *,
        index: int,
        colour: tuple[float, float, float] | None = None,
        egy: str | None = None,
    ) -> None:
        nonlocal order
        skills.append(
            Skill(
                code=code,
                category=category,
                label_ar=label,
                label_vowelised=_placeholder_vowelised(label),
                label_egy=egy or label,
                transliteration=f"{PLACEHOLDER}:{code}",
                phonemes=_placeholder_phonemes(code),
                difficulty_tier=_tier_for(category, index),
                intro_order=order,
                alt_text_ar=f"[{PLACEHOLDER}] صورة {label}",
                colour=colour,
            )
        )
        order += 1

    # Order matters: the earliest categories are the most concrete and the most
    # present in a child's daily life, which is where errorless learning starts.
    for index, (suffix, label, coordinates) in enumerate(COLOURS):
        add(f"color_{suffix}", "colors", label, index=index, colour=coordinates)
    for index, (suffix, label) in enumerate(BODY_PARTS):
        add(f"body_{suffix}", "body_parts", label, index=index)
    for index, (suffix, label) in enumerate(SOCIAL):
        add(f"social_{suffix}", "social", label, index=index)
    for index, (suffix, label) in enumerate(HOUSEHOLD):
        add(f"hh_{suffix}", "household", label, index=index)
    for index, (suffix, glyph, word) in enumerate(NUMERALS):
        add(f"num_{suffix}", "numbers", glyph, index=index, egy=word)
    for index, (name, glyph) in enumerate(LETTERS):
        keyword = LETTER_KEYWORDS.get(name)
        add(
            f"letter_{name}",
            "letters",
            glyph,
            index=index,
            # A SINGLE token: the real keyword words are one word each
            # (أ → أسد), and a multi-word placeholder would silently push
            # every instruction over the 5-word limit and mask the real
            # constraint. Still visibly a placeholder.
            egy=keyword or f"{PLACEHOLDER}-{glyph}",
        )

    return _attach_distractor_pools(skills)


def _attach_distractor_pools(skills: list[Skill]) -> list[Skill]:
    """Give every skill at least MIN_DISTRACTORS candidates.

    PLACEHOLDER. docs/04c §C05 requires these to be HAND-CURATED so that wrong
    answers are perceptually and semantically distinct — "a red card must never
    sit next to an orange card at tier 1". This function cannot do that: it
    simply offers every skill outside the target's own category, and leaves the
    real discrimination work to `choose_distractors`, which applies the
    contrast rules at selection time.

    A curated pool is still required before launch. → REVIEW-QUEUE.md #6
    """
    by_category: dict[str, list[str]] = {}
    for skill in skills:
        by_category.setdefault(skill.category, []).append(skill.code)

    resolved: list[Skill] = []
    for skill in skills:
        pool = [
            code
            for category, codes in by_category.items()
            if category != skill.category
            for code in codes
        ]
        # Deterministic spread rather than a random sample, so the seed is
        # reproducible and a diff is readable.
        stride = max(1, len(pool) // 12)
        selected = tuple(pool[::stride][:12])
        resolved.append(
            Skill(
                code=skill.code,
                category=skill.category,
                label_ar=skill.label_ar,
                label_vowelised=skill.label_vowelised,
                label_egy=skill.label_egy,
                transliteration=skill.transliteration,
                phonemes=skill.phonemes,
                difficulty_tier=skill.difficulty_tier,
                intro_order=skill.intro_order,
                alt_text_ar=skill.alt_text_ar,
                colour=skill.colour,
                distractor_pool=selected,
                prerequisites=skill.prerequisites,
            )
        )
    return resolved


# --- activity templates, docs/02 §10.2 -------------------------------------


@dataclass(frozen=True, slots=True)
class ActivityTemplate:
    code: str
    kind: str
    modality: str
    choice_count: int
    #: MUST be <= 5 words after {label} substitution (docs/06 §4).
    instruction_ar: str
    success_audio_pool: tuple[str, ...]
    retry_audio_pool: tuple[str, ...]
    min_tier: int


#: PLACEHOLDER Arabic. Every string here is spoken to a child and must be
#: reviewed by a native speaker. The success lines are warm; the retry lines are
#: gentle and NEVER corrective — there is no failure state in this product.
SUCCESS_POOL: tuple[str, ...] = ("برافو!", "شاطر أوي!", "أحسنت!", "تمام!")
RETRY_POOL: tuple[str, ...] = ("يلا نجرب تاني", "خد وقتك", "تعالى نشوف")

ACTIVITY_TEMPLATES: tuple[ActivityTemplate, ...] = (
    ActivityTemplate(
        "listen_point_2choice",
        "listen_point",
        "receptive",
        2,
        "وريني {label}",
        SUCCESS_POOL,
        RETRY_POOL,
        1,
    ),
    ActivityTemplate(
        "listen_point_3choice",
        "listen_point",
        "receptive",
        3,
        "وريني {label}",
        SUCCESS_POOL,
        RETRY_POOL,
        2,
    ),
    ActivityTemplate(
        "listen_point_4choice",
        "listen_point",
        "receptive",
        4,
        "وريني {label}",
        SUCCESS_POOL,
        RETRY_POOL,
        3,
    ),
    ActivityTemplate(
        "match_pair_picture",
        "match_pair",
        "receptive",
        2,
        "هات زي {label}",
        SUCCESS_POOL,
        RETRY_POOL,
        2,
    ),
    ActivityTemplate(
        "match_pair_word",
        "match_pair",
        "receptive",
        2,
        "وصّل {label}",
        SUCCESS_POOL,
        RETRY_POOL,
        3,
    ),
    ActivityTemplate(
        "say_it_word",
        "say_it",
        "expressive",
        1,
        "قول {label}",
        SUCCESS_POOL,
        RETRY_POOL,
        2,
    ),
    ActivityTemplate(
        "say_it_repeat_after",
        "say_it",
        "expressive",
        1,
        "قول ورايا {label}",
        SUCCESS_POOL,
        RETRY_POOL,
        1,
    ),
    ActivityTemplate(
        "sort_category_2bin",
        "sort_category",
        "receptive",
        2,
        "حط {label} هنا",
        SUCCESS_POOL,
        RETRY_POOL,
        3,
    ),
    ActivityTemplate(
        "story_moment_3frame",
        "story_moment",
        "receptive",
        3,
        "فين {label}",
        SUCCESS_POOL,
        RETRY_POOL,
        2,
    ),
)
