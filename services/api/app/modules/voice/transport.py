"""The HTTP seam for ASR. Deliberately not in `providers.py`.

`providers.py` says why: "the module that handles child audio has no reason to
be able to make an arbitrary request, and the cheapest way to guarantee that is
for the capability not to be in scope." So the protocol lives there and the one
implementation that can actually reach a network lives here.

This speaks the OpenAI-compatible transcription API, which covers both
recognisers in docs/12 §3: the self-hosted Qwen3-ASR behind vLLM, and Groq's
Whisper endpoint used as failover. Plain `httpx` rather than the Groq SDK --
`tools/guards/single_anthropic_client.py` forbids a provider client outside the
gateway, and docs/04d §5 keeps the voice path away from the gateway entirely.
No audio, no transcript and no embedding ever reaches the LLM.
"""

from __future__ import annotations

import math
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)


class HttpxAsrTransport:
    """POSTs audio to an OpenAI-compatible `/audio/transcriptions`.

    A client per call. The alternative -- a pooled client -- needs a lifecycle
    this module would have to own, and at a few requests per play session the
    handshake is a small fraction of a 5-second budget. Pass `client` to share
    one when that stops being true.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = client

    async def post_audio(
        self,
        *,
        model: str,
        audio: bytes,
        language: str,
        prompt: str,
        n_best: int,
        timeout_s: float,
    ) -> dict[str, Any]:
        # `verbose_json` is what carries `segments[].avg_logprob`, and that is
        # the only confidence signal Whisper offers.
        data: dict[str, str] = {
            "model": model,
            "language": language.split("-")[0],
            "response_format": "verbose_json",
            # Greedy. A sampled transcript of a child's single word is a
            # different word some fraction of the time.
            "temperature": "0",
        }
        if prompt:
            # Phrase hints. docs/04d §3 calls this the single biggest accuracy
            # lever on short utterances.
            data["prompt"] = prompt

        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        url = f"{self._base_url}/audio/transcriptions"
        files = {"file": ("attempt.ogg", audio, "audio/ogg")}

        if self._client is not None:
            response = await self._client.post(
                url, data=data, files=files, headers=headers, timeout=timeout_s
            )
        else:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                response = await client.post(url, data=data, files=files, headers=headers)
        response.raise_for_status()
        payload: dict[str, Any] = response.json()

        text = str(payload.get("text", "")).strip()
        return {
            "text": text,
            "confidence": _confidence(payload),
            # Note what is NOT returned: `segments`. `HttpAsrProvider` reads that
            # key as n-best alternatives, and Whisper's segments are sequential
            # chunks of one transcript, not competing hypotheses. Returning them
            # would hand the scorer the second half of a sentence as if it were
            # a rival reading of the first. Whisper gives no n-best; one
            # hypothesis is the truthful answer, and `n_best` is accepted here
            # only because the protocol passes it.
        }


def _confidence(payload: dict[str, Any]) -> float:
    """Mean segment log-probability, exponentiated back into 0..1.

    Absent `segments` -- which is what a plain-JSON response or an empty
    transcript gives -- this is 0.0 rather than a guess. The scorer treats a
    zero-confidence hypothesis as unusable, which is the correct handling of
    "the recogniser did not tell us".
    """
    segments = payload.get("segments")
    if not isinstance(segments, list) or not segments:
        return 0.0
    logprobs = [
        float(segment["avg_logprob"])
        for segment in segments
        if isinstance(segment, dict) and isinstance(segment.get("avg_logprob"), int | float)
    ]
    if not logprobs:
        return 0.0
    return round(math.exp(sum(logprobs) / len(logprobs)), 4)


__all__ = ["HttpxAsrTransport"]
