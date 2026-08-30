"""Arabic orthographic normalisation.

Everything that reaches the pronunciation scorer passes through here first,
because ASR output and a curriculum label are written by different hands and
Arabic gives you several ways to write the same sound.

The transformations are the ones docs/04d §3 names, and no others. In
particular this does **not** strip the definite article, expand numerals, or
correct spelling: those change the word, and a scorer that quietly rewrites the
child's attempt into the expected answer is not measuring anything.

Pure. No I/O.
"""

from __future__ import annotations

import re

#: Combining marks: fathatan..sukun, plus superscript alef and the Quranic
#: annotation range that occasionally survives a copy-paste.
TASHKEEL = "\u064b\u064c\u064d\u064e\u064f\u0650\u0651\u0652\u0653\u0654\u0655\u0670"

#: Kashida / tatweel — a purely typographic stretch with no phonetic value.
TATWEEL = "\u0640"

#: Every hamza carrier collapses to bare alef. ASR is unreliable about which
#: carrier it emits and the distinction is never phonemic in these 88 words.
ALEF_FORMS = "\u0623\u0625\u0622\u0671"  # أ إ آ ٱ

_TASHKEEL_RE = re.compile(f"[{TASHKEEL}]")
_TATWEEL_RE = re.compile(TATWEEL)
_ALEF_RE = re.compile(f"[{ALEF_FORMS}]")
_WHITESPACE_RE = re.compile(r"\s+")

#: Punctuation an ASR provider adds and a caregiver never says. Arabic comma,
#: Arabic question mark and Arabic semicolon are included deliberately.
_PUNCTUATION_RE = re.compile(r"[.,!?;:\u060c\u061b\u061f\u2026\"'`\u00ab\u00bb\-_()\[\]]")

#: Arabic-Indic digits, so a numeral heard as "٣" matches one written as "3".
_ARABIC_INDIC = str.maketrans(
    "\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669", "0123456789"
)


def strip_tashkeel(text: str) -> str:
    return _TASHKEEL_RE.sub("", text)


def normalize_ar(text: str) -> str:
    """Canonical form for comparison.

    tashkeel removed · tatweel removed · أ إ آ ٱ → ا · ة → ه · ى → ي ·
    Arabic-Indic digits → ASCII · punctuation dropped · whitespace collapsed.

    ``ة → ه`` is the orthographic half of the rule; the phonetic half (a final
    ``ه`` is realised as /a/, not /h/) lives in :mod:`app.modules.voice.domain.g2p`
    so that both sides of a comparison get it identically.
    """
    text = strip_tashkeel(text)
    text = _TATWEEL_RE.sub("", text)
    text = _ALEF_RE.sub("\u0627", text)
    text = text.replace("\u0629", "\u0647")  # ة → ه
    text = text.replace("\u0649", "\u064a")  # ى → ي
    text = text.translate(_ARABIC_INDIC)
    text = _PUNCTUATION_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", text).strip()
