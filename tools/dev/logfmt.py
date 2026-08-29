"""One readable stream out of three processes that log in three formats.

The API emits structlog JSON (one object per line, field allow-list already
applied). Next.js emits ANSI-decorated prose. Docker emits whatever the image
felt like. Reading three terminals to follow one request is the actual friction
this file removes.

Two rules shape everything here:

* **Never invent a field.** The API's log line has already been through
  `app.core.logging.field_allow_list`, which drops anything not explicitly
  permitted. This formatter re-renders what survived; it never reaches back for
  what was dropped, and it never re-adds a `dropped_fields` value to the human
  line. If a field is not in the JSON it does not exist.
* **The file on disk is the raw stream.** Colour and alignment are for the
  terminal. `logs/dev-*.log` gets the unformatted source line, so a bug report
  can carry the real JSON rather than this file's opinion of it.

Pure. `run.py` does the I/O.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

RESET = "\x1b[0m"
DIM = "\x1b[2m"
BOLD = "\x1b[1m"

#: One colour per process, stable across runs so the eye learns them.
SOURCE_COLOURS: dict[str, str] = {
    "api": "\x1b[38;5;80m",  # cyan
    "web": "\x1b[38;5;141m",  # violet
    "docker": "\x1b[38;5;245m",  # grey
    "dev": "\x1b[38;5;114m",  # green — the runner's own voice
    "worker": "\x1b[38;5;180m",  # sand
}

LEVEL_COLOURS: dict[str, str] = {
    "critical": "\x1b[38;5;197m",
    "error": "\x1b[38;5;203m",
    "warning": "\x1b[38;5;214m",
    "info": "\x1b[38;5;252m",
    "debug": "\x1b[38;5;244m",
}


#: HTTP status → colour. Bands, not codes: 2xx is quiet, 4xx is the caller's
#: problem and worth noticing, 5xx is ours and should be impossible to miss.
def status_colour(status: int) -> str:
    if status >= 500:
        return "\x1b[38;5;197m"
    if status >= 400:
        return "\x1b[38;5;214m"
    if status >= 300:
        return "\x1b[38;5;245m"
    return "\x1b[38;5;114m"


#: Fields rendered inline after the event name, in this order. Everything else
#: in the record is appended as key=value. The order is "what identifies the
#: work" before "what it cost".
INLINE_ORDER: tuple[str, ...] = (
    "decision_point",
    "provider",
    "model",
    "guardrail_layer",
    "guardrail_outcome",
    "outcome",
    "reason",
    "child_id",
    "session_id",
    "activity_id",
    "skill_id",
    "attempt",
    "count",
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "latency_ms",
)

#: Never shown inline — they are structure, not content.
STRUCTURAL: frozenset[str] = frozenset(
    {"event", "level", "logger", "timestamp", "service", "request_id"}
)


@dataclass(frozen=True, slots=True)
class Line:
    """A formatted terminal line plus the raw text that produced it."""

    text: str
    raw: str
    #: True for anything at warning or above, so `run.py` can also mirror it to
    #: stderr without re-parsing.
    is_problem: bool = False


def _short_request_id(value: str) -> str:
    """First segment of a uuid. Enough to correlate by eye within one session."""
    return value.split("-")[0]


def _render_http(record: dict[str, Any], *, colour: bool) -> str:
    method = str(record.get("method", "?"))
    path = str(record.get("path", "?"))
    status = int(record.get("status_code", 0) or 0)
    duration = record.get("duration_ms")
    tint = status_colour(status) if colour else ""
    reset = RESET if colour else ""
    dim = DIM if colour else ""
    duration_text = f"{float(duration):.1f}ms" if duration is not None else "?"
    parts = [f"{tint}{status:>3}{reset}", f"{method:<6}", path, f"{dim}{duration_text}{reset}"]
    request_id = record.get("request_id")
    if request_id:
        parts.append(f"{dim}req={_short_request_id(str(request_id))}{reset}")
    return " ".join(parts)


def format_json_record(record: dict[str, Any], *, colour: bool = True) -> str:
    """Render one structlog record as a human line."""
    level = str(record.get("level", "info")).lower()
    reset = RESET if colour else ""
    dim = DIM if colour else ""
    level_tint = LEVEL_COLOURS.get(level, "") if colour else ""
    event = str(record.get("event", ""))

    if event == "http_request":
        return _render_http(record, colour=colour)

    head = f"{level_tint}{event}{reset}" if event else ""
    rest: list[str] = []
    for key in INLINE_ORDER:
        if key in record and record[key] is not None:
            rest.append(f"{dim}{key}={reset}{record[key]}")
    for key, value in record.items():
        if key in STRUCTURAL or key in INLINE_ORDER or value is None:
            continue
        rest.append(f"{dim}{key}={reset}{value}")
    request_id = record.get("request_id")
    if request_id:
        rest.append(f"{dim}req={_short_request_id(str(request_id))}{reset}")
    return " ".join([head, *rest]).strip()


def is_problem_level(record: dict[str, Any]) -> bool:
    return str(record.get("level", "")).lower() in {"warning", "error", "critical", "exception"}


def format_line(source: str, raw: str, *, colour: bool = True, clock: str = "") -> Line:
    """Format one line of output from one child process.

    A line that parses as a JSON object is treated as a structlog record. A line
    that does not is passed through unchanged — Next.js, uvicorn's own startup
    banner and docker all emit prose, and rewriting prose is how a runner starts
    hiding the message a developer needed.
    """
    stripped = raw.rstrip("\r\n")
    record: dict[str, Any] | None = None
    candidate = stripped.strip()
    if candidate.startswith("{") and candidate.endswith("}"):
        try:
            parsed = json.loads(candidate)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, dict):
            record = parsed

    if record is not None:
        body = format_json_record(record, colour=colour)
        problem = is_problem_level(record)
    else:
        body = stripped
        problem = False

    tint = SOURCE_COLOURS.get(source, "") if colour else ""
    reset = RESET if colour else ""
    dim = DIM if colour else ""
    prefix = f"{dim}{clock}{reset} {tint}{source:<6}{reset}{dim}│{reset} " if clock else ""
    return Line(text=f"{prefix}{body}", raw=stripped, is_problem=problem)


def banner(title: str, rows: list[tuple[str, str]], *, colour: bool = True) -> str:
    """A two-column block. Used for the URL table and the preflight report."""
    bold = BOLD if colour else ""
    dim = DIM if colour else ""
    reset = RESET if colour else ""
    if not rows:
        return f"{bold}{title}{reset}"
    width = max(len(left) for left, _ in rows)
    lines = [f"{bold}{title}{reset}"]
    lines.extend(f"  {left.ljust(width)}  {dim}{right}{reset}" for left, right in rows)
    return "\n".join(lines)
