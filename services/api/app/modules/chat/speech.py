"""Speech ports for chat — deliberately stubbed, and honest about it.

**Nothing here synthesises or recognises anything yet.** That was the decision:
the vendor question is open, so this file defines the seam and returns a
`supported: false` capability rather than a guess.

What that means concretely, and why each half is shaped the way it is.

**Text to speech.** There is no runtime TTS provider anywhere in this product,
by design rather than by omission -- docs/12 §3 pre-renders Nour's corpus so her
voice cannot drift (Assumption C7), and `voice/providers.py` says a synthesis
request in the request path can only ever be a cache read. That works for the
child surface, whose replies are the seven reviewed phrases in `domain.py`, each
with an `audio_key` into that corpus. It does not work for the caregiver
assistant, whose answers are generated and therefore have no rendered file. So
the caregiver surface returns text and the **client speaks it** with the
browser's SpeechSynthesis -- no vendor, no key, no audio leaving the device.
`TtsPort` exists so a server-side vendor can be dropped in later without the
route changing.

**Speech to text.** The recogniser is already built and already wired:
`AsrChain` in `voice/providers.py`, reached through `HttpxAsrTransport`, running
Groq Whisper today. It is not reused here, and the reason is a real constraint
rather than tidiness -- `voice/service.py` is scoped to scoring a single
expected word against a curriculum label, it requires `voice_asr` consent for a
child's audio, and it deletes the bytes in a `finally`. A caregiver dictating a
question is a different act with a different legal basis and a different
retention answer. `SttPort` is where that lands when the question is settled.

Until then both ports have exactly one implementation, `Unavailable`, which
answers `supported: false`. The route returns 501 rather than 500, and the
client feature-detects and falls back to typing. A stub that returned empty
text would be worse than one that refuses: the caller cannot tell "we heard
nothing" from "we did not listen".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import structlog

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SpeechCapability:
    """What the client should feature-detect against.

    `client_fallback` names what the browser should do instead. The client
    reads it rather than hard-coding the answer, so switching a surface onto a
    server implementation later is a config change on one side, not a release
    on both.
    """

    supported: bool
    provider: str
    client_fallback: str
    detail_ar: str


UNAVAILABLE_TTS = SpeechCapability(
    supported=False,
    provider="none",
    client_fallback="browser_speech_synthesis",
    detail_ar="الصوت بيتقري من المتصفح دلوقتي.",
)

UNAVAILABLE_STT = SpeechCapability(
    supported=False,
    provider="none",
    client_fallback="browser_speech_recognition",
    detail_ar="التسجيل بيتحوّل لكلام من المتصفح دلوقتي.",
)


class SpeechUnavailableError(RuntimeError):
    """Raised by every port method here. The router maps it to 501."""


@runtime_checkable
class TtsPort(Protocol):
    name: str

    def capability(self) -> SpeechCapability: ...

    async def synthesize(self, text_ar: str, *, voice: str = "nour") -> bytes: ...


@runtime_checkable
class SttPort(Protocol):
    name: str

    def capability(self) -> SpeechCapability: ...

    async def transcribe(self, audio: bytes, *, language: str = "ar-EG") -> str: ...


class UnavailableTts:
    """No server-side synthesis. The browser speaks the text."""

    name = "none"

    def capability(self) -> SpeechCapability:
        return UNAVAILABLE_TTS

    async def synthesize(self, text_ar: str, *, voice: str = "nour") -> bytes:
        raise SpeechUnavailableError("no server-side TTS provider is configured")


class UnavailableStt:
    """No server-side recognition on the chat path. The browser listens."""

    name = "none"

    def capability(self) -> SpeechCapability:
        return UNAVAILABLE_STT

    async def transcribe(self, audio: bytes, *, language: str = "ar-EG") -> str:
        raise SpeechUnavailableError("no server-side chat STT provider is configured")


def prerendered_audio_key(phrase_id: str) -> str | None:
    """The rendered clip for a child-surface phrase, if the corpus has one.

    The child surface needs no synthesis at all: every reply it can produce is
    one of the seven reviewed phrases, and each carries its key into the
    pre-rendered corpus. This is the whole reason that surface is a closed set.
    """
    from app.modules.chat.domain import CHILD_PHRASES_BY_ID

    phrase = CHILD_PHRASES_BY_ID.get(phrase_id)
    return phrase.audio_key if phrase else None


__all__ = [
    "UNAVAILABLE_STT",
    "UNAVAILABLE_TTS",
    "SpeechCapability",
    "SpeechUnavailableError",
    "SttPort",
    "TtsPort",
    "UnavailableStt",
    "UnavailableTts",
    "prerendered_audio_key",
]
