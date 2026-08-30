"""Upload validation, before anything touches a provider or the disk.

docs/04d §5. The rules are short and the order they run in is the whole point:
size is checked before the bytes are inspected, and the container is decided by
**magic bytes**, never by the filename or the declared content type. A client
can say anything; a RIFF header cannot.

Pure. No I/O — the caller holds the bytes.
"""

from __future__ import annotations

from dataclasses import dataclass

#: docs/04d §5 — a 6-second utterance at 24 kbps is ~18 KB. 1 MB is three
#: orders of magnitude of headroom and still bounds a malicious upload.
MAX_UPLOAD_BYTES = 1024 * 1024

#: Above this the bytes go to a temp file instead of staying in memory.
IN_MEMORY_LIMIT_BYTES = 256 * 1024

#: Hard cap on utterance length (docs/04d §3 VAD table).
MAX_DURATION_SECONDS = 6.0


class AudioRejected(ValueError):
    """The upload is not usable. `reason` is a stable machine code."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class Container:
    name: str
    mime: str


WEBM = Container("webm", "audio/webm")
OGG = Container("ogg", "audio/ogg")
WAV = Container("wav", "audio/wav")
MP4 = Container("m4a", "audio/mp4")

#: (offset, signature, container). Checked in order; first hit wins.
SIGNATURES: tuple[tuple[int, bytes, Container], ...] = (
    (0, b"\x1a\x45\xdf\xa3", WEBM),  # EBML — webm and mkv
    (0, b"OggS", OGG),  # Ogg, which is how Opus usually arrives
    (0, b"RIFF", WAV),  # RIFF....WAVE
    (4, b"ftyp", MP4),  # ISO base media, offset 4
)


def sniff(data: bytes) -> Container | None:
    """The container these bytes actually are, or None."""
    for offset, signature, container in SIGNATURES:
        if data[offset : offset + len(signature)] == signature:
            if container is WAV and data[8:12] != b"WAVE":
                continue
            return container
    return None


def validate_upload(data: bytes, *, max_bytes: int = MAX_UPLOAD_BYTES) -> Container:
    """Raise `AudioRejected`, or return the sniffed container.

    Empty is rejected separately from unrecognised, because they mean different
    things: empty is usually a client that recorded nothing, unrecognised is
    usually a client sending the wrong thing entirely.
    """
    if not data:
        raise AudioRejected("empty_audio")
    if len(data) > max_bytes:
        raise AudioRejected("audio_too_large")
    container = sniff(data)
    if container is None:
        raise AudioRejected("unrecognised_audio_container")
    return container


def needs_temp_file(data: bytes) -> bool:
    return len(data) > IN_MEMORY_LIMIT_BYTES
