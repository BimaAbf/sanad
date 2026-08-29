"""ASR and TTS behind protocols, plus the failover chain.

docs/12 §Δ2 replaced the vendors and left the shape alone, which is the point of
having had a protocol here in the first place:

    Qwen3-ASR-1.7B (self-hosted, vLLM)  →  Groq Whisper  →  caregiver confirmation

TTS has no runtime provider at all any more. `NullTts` remains for tests and
`PreRenderedTts` is a lookup against the rendered corpus, so a "synthesis"
request in the request path can only ever be a cache read — which is exactly the
invariant the child app's zero-TTS-calls test asserts.

Nothing in this module reaches the LLM gateway. That is not an accident of
layering; audio, transcripts and embeddings are forbidden from crossing that
boundary (docs/04d §5), and the way to keep them from crossing it is for this
module never to import it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

import structlog

from app.modules.voice.domain.scoring import AsrResult, Hypothesis

logger = structlog.get_logger(__name__)


class AsrUnavailable(RuntimeError):
    """Raised by a provider that could not answer at all."""


@runtime_checkable
class AsrProvider(Protocol):
    name: str

    async def transcribe(
        self,
        audio: bytes,
        *,
        language: str = "ar-EG",
        phrase_hints: list[str] | None = None,
        n_best: int = 5,
    ) -> AsrResult: ...


@runtime_checkable
class TtsProvider(Protocol):
    name: str

    async def synthesize(
        self, ssml: str, voice: str, fmt: str = "ogg-48khz-16bit-mono-opus"
    ) -> bytes: ...


class NullAsr:
    """Scripted transcripts. The CI default.

    `script` maps a phrase hint to the hypotheses to return, so a test can say
    "when the expected word is أحمر, the recogniser hears أحم" without owning
    any audio.
    """

    name = "null"

    def __init__(
        self,
        script: dict[str, list[str]] | None = None,
        *,
        default: list[str] | None = None,
        fail: bool = False,
    ) -> None:
        self._script = script or {}
        self._default = default or []
        self._fail = fail
        self.calls = 0

    async def transcribe(
        self,
        audio: bytes,
        *,
        language: str = "ar-EG",
        phrase_hints: list[str] | None = None,
        n_best: int = 5,
    ) -> AsrResult:
        self.calls += 1
        if self._fail:
            raise AsrUnavailable(self.name)
        texts = self._default
        for hint in phrase_hints or []:
            if hint in self._script:
                texts = self._script[hint]
                break
        hypotheses = tuple(
            Hypothesis(text=text, confidence=max(0.0, 1.0 - 0.1 * index))
            for index, text in enumerate(texts[:n_best])
        )
        return AsrResult(n_best=hypotheses, provider=self.name)


class NullTts:
    """A fixed 200 ms tone, as docs/04d §2 specifies for tests."""

    name = "null"
    #: An Ogg page header followed by silence — enough for the magic-byte
    #: sniffer to recognise it, which is all a test needs.
    TONE = b"OggS" + b"\x00" * 396

    def __init__(self) -> None:
        self.calls = 0

    async def synthesize(
        self, ssml: str, voice: str, fmt: str = "ogg-48khz-16bit-mono-opus"
    ) -> bytes:
        self.calls += 1
        return self.TONE


class PreRenderedTts:
    """Serves only what the offline renderer already produced.

    A miss is an error, not a synthesis. That is deliberate: after docs/12 §Δ2 a
    miss means the publish gate let a gap through, and quietly synthesising
    would hide it until a child sat in silence.
    """

    name = "prerendered"

    def __init__(self, corpus: dict[str, bytes]) -> None:
        self._corpus = corpus
        self.calls = 0

    async def synthesize(
        self, ssml: str, voice: str, fmt: str = "ogg-48khz-16bit-mono-opus"
    ) -> bytes:
        self.calls += 1
        try:
            return self._corpus[ssml]
        except KeyError as exc:
            raise LookupError("utterance not in the rendered corpus") from exc


class AsrTransport(Protocol):
    """The one seam through which this module could reach a network.

    Kept as a protocol so nothing here imports an HTTP client: the module that
    handles child audio has no reason to be able to make an arbitrary request,
    and the cheapest way to guarantee that is for the capability not to be in
    scope.
    """

    async def post_audio(
        self,
        *,
        model: str,
        audio: bytes,
        language: str,
        prompt: str,
        n_best: int,
        timeout_s: float,
    ) -> dict[str, Any]: ...


class HttpAsrProvider:
    """Shared body of the two real recognisers.

    Both speak an OpenAI-compatible transcription endpoint — the self-hosted
    vLLM server because DigitalTwins configures it that way, and Groq because it
    is Groq. The differences that remain are the URL, the model id and the
    credential, so they are constructor arguments rather than two classes with
    the same code in them.
    """

    def __init__(
        self,
        *,
        name: str,
        model: str,
        transport: AsrTransport,
        timeout_s: float = 5.0,
    ) -> None:
        self.name = name
        self._model = model
        self._transport = transport
        self._timeout_s = timeout_s

    async def transcribe(
        self,
        audio: bytes,
        *,
        language: str = "ar-EG",
        phrase_hints: list[str] | None = None,
        n_best: int = 5,
    ) -> AsrResult:
        try:
            payload = await self._transport.post_audio(
                model=self._model,
                audio=audio,
                language=language,
                # Phrase hints are the single biggest accuracy lever on short
                # utterances (docs/04d §3): biasing toward a three-word
                # hypothesis space is worth more than any model change.
                prompt=" ".join(phrase_hints or []),
                n_best=n_best,
                timeout_s=self._timeout_s,
            )
        except Exception as exc:
            logger.info("asr_provider_failed", provider=self.name, exc_type=type(exc).__name__)
            raise AsrUnavailable(self.name) from exc

        raw = payload.get("segments")
        if not raw:
            text = payload.get("text")
            raw = [text] if text else []
        hypotheses = tuple(
            Hypothesis(text=str(item), confidence=float(payload.get("confidence", 0.0)))
            for item in list(raw)[:n_best]
        )
        return AsrResult(n_best=hypotheses, provider=self.name)


def qwen_provider(
    transport: AsrTransport, *, model: str = "Qwen/Qwen3-ASR-1.7B"
) -> HttpAsrProvider:
    """Primary. Self-hosted, and the only path to a fine-tune (docs/12 §3.2)."""
    return HttpAsrProvider(name="qwen", model=model, transport=transport)


def groq_whisper_provider(
    transport: AsrTransport, *, model: str = "whisper-large-v3-turbo"
) -> HttpAsrProvider:
    """Failover. Free-tier audio-seconds cover the pilot ~120x (docs/12 §1)."""
    return HttpAsrProvider(name="groq_whisper", model=model, transport=transport)


class AsrChain:
    """Try each provider in order; the first that answers wins.

    Returns `AsrResult(unavailable=True)` rather than raising when every
    provider is down, because "nobody could listen" is a normal state of this
    product and the caller has a defined behaviour for it. Raising would make
    the common path an exception path.
    """

    def __init__(self, providers: Sequence[AsrProvider]) -> None:
        self._providers = providers

    @property
    def provider_names(self) -> list[str]:
        return [provider.name for provider in self._providers]

    async def transcribe(
        self, audio: bytes, *, phrase_hints: list[str] | None = None, n_best: int = 5
    ) -> AsrResult:
        for provider in self._providers:
            try:
                result = await provider.transcribe(audio, phrase_hints=phrase_hints, n_best=n_best)
            except AsrUnavailable:
                continue
            if result.n_best:
                return result
            # An empty answer is not a failure of the provider, but it is worth
            # a second opinion — which is exactly why there is a second one.
            logger.info("asr_empty_result", provider=provider.name)
        return AsrResult(unavailable=True, provider="none")
