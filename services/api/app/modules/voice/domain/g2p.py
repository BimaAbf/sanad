"""Arabic grapheme-to-phoneme for the closed vocabulary of the 88 skills.

This is deliberately a *rule table*, not a model. The vocabulary is fixed and
tiny, the output feeds a similarity metric rather than a synthesiser, and a
statistical g2p would make the scorer's behaviour unauditable — which matters,
because the thing it decides is whether a child is told they said a word right.

Egyptian colloquial, not MSA. The two places that diverge and matter:

  ج → /g/   (جزمة is /gazma/, never /dʒazma/ — docs/12 §3.5 makes this the
             reason Saudi-dialect TTS was rejected outright)
  ق → /ʔ/   in colloquial words, /q/ in the letter-name and Quranic register.
             We emit /ʔ/ and let the emphatic↔plain rule absorb the difference,
             which costs 0.2 either way rather than 1.0.

PLACEHOLDER STATUS: the mapping below is transcribed from standard descriptions
of Egyptian Arabic phonology, not reviewed by a phonetician or a speech-language
therapist. `seeds/curriculum.py` ships `phonemes` as an explicit placeholder, so
this function — not that column — is what the scorer actually uses today. When a
reviewed phoneme column arrives it supersedes this. → REVIEW-QUEUE.md

Pure. No I/O.
"""

from __future__ import annotations

from app.modules.voice.domain.normalize import normalize_ar

#: One ASCII character per phoneme, so similarity is a string edit distance and
#: the cost matrix is readable. The letters are mnemonic, not IPA: IPA needs
#: multi-codepoint sequences for the emphatics and that would silently make an
#: emphatic substitution cost two edits instead of one.
#:
#:   b t s g H x d z r $ S D T Z 3 G f q k l m n h w y 2
#:   a i u  short vowels        A I U  long vowels
CONSONANTS = frozenset("btsgHxdzr$SDTZ3GfqklmnhwyRvp2")
SHORT_VOWELS = frozenset("aiu")
LONG_VOWELS = frozenset("AIU")
VOWELS = SHORT_VOWELS | LONG_VOWELS

LETTER_TO_PHONEME: dict[str, str] = {
    "\u0627": "A",  # ا  long a
    "\u0628": "b",  # ب
    "\u062a": "t",  # ت
    "\u062b": "s",  # ث  Egyptian merges into /s/
    "\u062c": "g",  # ج  /g/ — Egyptian
    "\u062d": "H",  # ح
    "\u062e": "x",  # خ
    "\u062f": "d",  # د
    "\u0630": "z",  # ذ  Egyptian merges into /z/
    "\u0631": "r",  # ر
    "\u0632": "z",  # ز
    "\u0633": "s",  # س
    "\u0634": "$",  # ش
    "\u0635": "S",  # ص  emphatic
    "\u0636": "D",  # ض  emphatic
    "\u0637": "T",  # ط  emphatic
    "\u0638": "Z",  # ظ  emphatic
    "\u0639": "3",  # ع
    "\u063a": "G",  # غ
    "\u0641": "f",  # ف
    "\u0642": "2",  # ق  → glottal stop in colloquial
    "\u0643": "k",  # ك
    "\u0644": "l",  # ل
    "\u0645": "m",  # م
    "\u0646": "n",  # ن
    "\u0647": "h",  # ه
    "\u0648": "U",  # و  long u (as a glide it is /w/; see below)
    "\u064a": "I",  # ي  long i (as a glide it is /y/; see below)
    "\u0621": "2",  # ء
}

#: و and ي are the only ambiguous graphemes: vowel between consonants, glide
#: next to a vowel or at a word edge.
GLIDES: dict[str, str] = {"\u0648": "w", "\u064a": "y"}

#: The definite article assimilates to a following "sun letter" — الشمس is
#: /a$$ams/, not /al$ams/. Without this, every article-bearing label would carry
#: a spurious /l/ and score a real attempt as a deletion.
SUN_LETTERS = frozenset(
    "\u062a\u062b\u062f\u0630\u0631\u0632\u0633\u0634\u0635\u0636\u0637\u0638\u0644\u0646"
)


def _phonemise_word(word: str) -> str:
    if not word:
        return ""

    out: list[str] = []
    chars = list(word)

    # The definite article. ال at the start is /al/ before a moon letter and a
    # doubled consonant before a sun letter.
    if len(chars) > 2 and chars[0] == "\u0627" and chars[1] == "\u0644":
        following = chars[2]
        if following in SUN_LETTERS:
            doubled = LETTER_TO_PHONEME.get(following, "")
            out.append("a")
            out.append(doubled)
            chars = chars[2:]
        else:
            out.append("a")
            out.append("l")
            chars = chars[2:]

    last = len(chars) - 1
    for index, char in enumerate(chars):
        phoneme = LETTER_TO_PHONEME.get(char)
        if phoneme is None:
            # Digits and anything else outside the Arabic block: pass through so
            # the numerals (١ normalised to 1) still compare. No whitespace
            # guard is needed — `g2p` normalises and splits on spaces first, so
            # a word never contains one.
            out.append(char)
            continue

        if char in GLIDES:
            previous = out[-1] if out else ""
            # A glide when it starts the word or sits next to a vowel; a long
            # vowel when it sits between consonants and carries the syllable.
            if index == 0 or previous in VOWELS:
                out.append(GLIDES[char])
                continue

        if char == "\u0647" and index == last and index > 0:
            # Word-final ه. After normalisation this is almost always a ة, which
            # Egyptian realises as /a/. Emitting /h/ here would make every
            # feminine noun end in a consonant that nobody pronounces, and the
            # final-consonant-deletion rule would then forgive a real error.
            out.append("a")
            continue

        out.append(phoneme)

    return "".join(out)


def g2p(text: str) -> str:
    """Phoneme string for already-normalised or raw Arabic text.

    Normalisation is applied defensively so a caller cannot get a different
    answer by forgetting it. Multi-word labels (صباح الخير) are joined without a
    separator: a word boundary is not a phoneme and inserting a marker would
    make "said it as one word" cost an edit.
    """
    normalised = normalize_ar(text)
    return "".join(_phonemise_word(word) for word in normalised.split(" ") if word)


def is_consonant(phoneme: str) -> bool:
    return phoneme in CONSONANTS
