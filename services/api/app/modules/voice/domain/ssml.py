"""The SSML template and the cache key.

Transcribed from docs/04d §2. Two numbers in here are tuned for auditory
short-term memory rather than for naturalness, and both will look like bugs to
someone optimising for a demo:

* ``rate="-15%"`` — the voice is deliberately slower than sounds good.
* a **600 ms trailing break** — the wait timer must not start until the child
  can tell the utterance has ended.

Text comes from the **vowelised** column. Unvowelised Arabic sent to a TTS
engine mispronounces reliably; docs/04d calls this the single most common
Arabic TTS bug, and it is the one that would teach a child the wrong word.

Pure. No I/O.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from xml.sax.saxutils import escape

#: docs/04d §2 — `children.audio_rate_pct`, default 85, adjustable 60-110.
DEFAULT_RATE_PCT = 85
MIN_RATE_PCT = 60
MAX_RATE_PCT = 110

DEFAULT_PITCH = "+4%"
LEAD_BREAK_MS = 300
TRAIL_BREAK_MS = 600

#: docs/04d §2 — the whole corpus is normalised to this so no clip is startling.
TARGET_LUFS = -16.0
LUFS_TOLERANCE = 1.0

DEFAULT_VOICE = "nour"


class UnvowelisedText(ValueError):
    """Raised when a caller tries to synthesise bare, undiacriticised Arabic."""


#: Any tashkeel mark. One is enough to tell a vowelised string from a bare one.
_TASHKEEL = set("\u064b\u064c\u064d\u064e\u064f\u0650\u0651\u0652\u0670")

#: Words that carry no vowelisable letters — numerals, Latin, punctuation.
_ARABIC_LETTERS = set(range(0x0621, 0x0653))


@dataclass(frozen=True, slots=True)
class Utterance:
    """One thing the product can say. `key` is stable across re-renders."""

    key: str
    text_vowelised: str
    emphasis: str = ""
    voice: str = DEFAULT_VOICE
    rate_pct: int = DEFAULT_RATE_PCT
    pitch: str = DEFAULT_PITCH
    #: 'skill' | 'instruction' | 'feedback' | 'pgee_item' | 'ui' | 'child_name'
    kind: str = "ui"


def needs_vowelisation(text: str) -> bool:
    """True when the text contains Arabic letters but no diacritics at all."""
    if any(char in _TASHKEEL for char in text):
        return False
    return any(ord(char) in _ARABIC_LETTERS for char in text)


def clamp_rate(rate_pct: int) -> int:
    return max(MIN_RATE_PCT, min(MAX_RATE_PCT, rate_pct))


def rate_attribute(rate_pct: int) -> str:
    """85 → "-15%". The template's rate is relative to normal speed."""
    return f"{clamp_rate(rate_pct) - 100:+d}%"


def build_ssml(utterance: Utterance, *, require_vowelised: bool = True) -> str:
    """The exact template from docs/04d §2.

    `require_vowelised` is a parameter and not a hard-coded check only so the
    renderer can report *every* unvowelised item in one pass instead of failing
    on the first. Nothing in the request path may pass False.
    """
    if require_vowelised and needs_vowelisation(utterance.text_vowelised):
        raise UnvowelisedText(utterance.key)

    body = escape(utterance.text_vowelised)
    if utterance.emphasis:
        target = escape(utterance.emphasis)
        if target in body:
            body = body.replace(target, f'<emphasis level="moderate">{target}</emphasis>', 1)

    return (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        'xml:lang="ar-EG">'
        f'<voice name="{escape(utterance.voice)}">'
        f'<prosody rate="{rate_attribute(utterance.rate_pct)}" '
        f'pitch="{escape(utterance.pitch)}">'
        f'<break time="{LEAD_BREAK_MS}ms"/>'
        f"{body}"
        f'<break time="{TRAIL_BREAK_MS}ms"/>'
        "</prosody></voice></speak>"
    )


def cache_key(utterance: Utterance, ssml: str) -> str:
    """sha256(voice|rate|pitch|ssml) — docs/04d §2.

    The SSML is part of the key, so changing the break lengths or the emphasis
    target invalidates exactly the affected clips and nothing else. That is what
    makes the renderer idempotent and a re-render cheap.
    """
    material = f"{utterance.voice}|{clamp_rate(utterance.rate_pct)}|{utterance.pitch}|{ssml}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def loudness_within_tolerance(measured_lufs: float) -> bool:
    return abs(measured_lufs - TARGET_LUFS) <= LUFS_TOLERANCE
