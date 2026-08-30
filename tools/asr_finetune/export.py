"""Export consented (audio, expected_word, confirmed) triples for a LoRA fine-tune.

docs/12 §3.2. This is the flywheel: the caregiver override button was designed
as a graceful fallback, and it turns out to also be the only mechanism that can
produce a training set for Egyptian-Arabic child speech in this population,
because that data does not otherwise exist.

Which makes this the most sensitive export in the product. Every row is a
recording of a child's voice. So:

    the exporter REFUSES, loudly, to emit a single row that lacks
    `voice_retention` consent — and it refuses per row, not per batch,
    so one consented child in a list cannot carry the others through.

There is no flag to disable that check. If you find yourself wanting one, the
answer is to fix the consent data, not this file.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

#: docs/04d §5 — consented audio lives 30 days. Anything older has expired and
#: must not be in the store, let alone in a training set.
MAX_AGE_DAYS = 30

#: docs/04d §3 — the per-child reference cap. Applied here too, so a single
#: talkative child cannot dominate the fine-tune.
MAX_PER_CHILD_PER_SKILL = 20


class ConsentViolation(RuntimeError):
    """A row without `voice_retention` reached the exporter. Always fatal."""


@dataclass(frozen=True, slots=True)
class Triple:
    child_id: str
    skill_code: str
    expected_word: str
    audio_key: str
    confirmed: bool
    recorded_at: dt.datetime
    voice_retention_granted: bool


@dataclass(frozen=True, slots=True)
class ExportStats:
    written: int
    skipped_unconfirmed: int
    skipped_expired: int
    skipped_over_cap: int


def _assert_consented(triples: Iterable[Triple]) -> list[Triple]:
    rows = list(triples)
    offenders = [row.audio_key for row in rows if not row.voice_retention_granted]
    if offenders:
        raise ConsentViolation(
            f"{len(offenders)} row(s) lack voice_retention consent; "
            f"first offending key: {offenders[0]}"
        )
    return rows


def select(triples: Sequence[Triple], *, now: dt.datetime) -> tuple[list[Triple], ExportStats]:
    """Filter to what may legitimately train a model.

    Consent is checked first and raises. Everything else merely filters — the
    difference is deliberate: an unconfirmed attempt is uninteresting, an
    unconsented one is a breach.
    """
    rows = _assert_consented(triples)

    skipped_unconfirmed = 0
    skipped_expired = 0
    skipped_over_cap = 0
    counts: dict[tuple[str, str], int] = {}
    selected: list[Triple] = []

    for row in sorted(rows, key=lambda item: item.recorded_at, reverse=True):
        if not row.confirmed:
            skipped_unconfirmed += 1
            continue
        if (now - row.recorded_at).days > MAX_AGE_DAYS:
            skipped_expired += 1
            continue
        key = (row.child_id, row.skill_code)
        if counts.get(key, 0) >= MAX_PER_CHILD_PER_SKILL:
            skipped_over_cap += 1
            continue
        counts[key] = counts.get(key, 0) + 1
        selected.append(row)

    return selected, ExportStats(
        written=len(selected),
        skipped_unconfirmed=skipped_unconfirmed,
        skipped_expired=skipped_expired,
        skipped_over_cap=skipped_over_cap,
    )


def to_jsonl(rows: Sequence[Triple]) -> str:
    """One JSON object per line, the shape the DigitalTwins trainer reads.

    `child_id` is not written. The trainer has no use for it, and a training set
    that identifies the children in it is a training set that cannot be shared
    with a partner or archived safely.
    """
    return "\n".join(
        json.dumps(
            {
                "audio": row.audio_key,
                "text": row.expected_word,
                "skill": row.skill_code,
                "language": "ar-EG",
            },
            ensure_ascii=False,
        )
        for row in rows
    )


def write(rows: Sequence[Triple], destination: Path) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(to_jsonl(rows) + ("\n" if rows else ""), encoding="utf-8")
    return len(rows)
