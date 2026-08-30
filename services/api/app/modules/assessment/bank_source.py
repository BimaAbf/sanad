"""The process-wide item bank.

One module-level cache. `Bank.build()` validates ordinal density over every
domain and the synthetic bank is 120 items; doing that per request would be 120
items of pointless work on every answer POST.

The bank is `seeds/item_bank.py` -- machine-generated scaffolding, watermarked
PLACEHOLDER, pending open decision O1. Loading it here rather than from a table
is deliberate and temporary: `assessment_items` is unmigrated, and blocking
persistence on the licensed bank would mean no assessment history at all. The
version string is pinned onto every assessment row, so answers recorded against
this bank stay identifiable once a real one lands.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.modules.assessment.domain.bank import Bank


@lru_cache(maxsize=4)
def get_bank(version: str | None = None) -> Bank:
    """The bank for `version`, or the current one when version is None.

    A version this process does not have is not an error the caller can do
    anything about: the answers are still replayable against the bank we do
    have, and `engine.replay` skips items the bank does not contain. So an
    unknown version returns the current bank rather than raising.
    """
    from seeds.item_bank import build_bank

    return build_bank()


def current_version() -> str:
    return get_bank().version


__all__ = ["ItemText", "current_version", "get_bank", "item_text", "watermark"]


@dataclass(frozen=True, slots=True)
class ItemText:
    """What a caregiver actually reads. Deliberately NOT on `BankItem`.

    The engine decides what to ask next from ordinals and verdicts alone; it has
    no use for Arabic. Keeping the text out of `domain/bank.py` is what lets the
    domain package stay pure and fully covered without a fixture stack.
    """

    prompt_ar: str
    prompt_ar_msa: str
    example_ar: str


@lru_cache(maxsize=1)
def _texts() -> dict[str, ItemText]:
    from seeds.item_bank import build_items

    return {
        item.id: ItemText(
            prompt_ar=item.prompt_ar,
            prompt_ar_msa=item.prompt_ar_msa,
            example_ar=item.example_ar,
        )
        for item in build_items()
    }


def item_text(item_id: str) -> ItemText | None:
    return _texts().get(item_id)


def watermark() -> str:
    """The bank's provenance warning, or empty once a reviewed bank lands.

    Returned on the assessment state so the runner can carry it on screen. A
    placeholder bank that looks exactly like a real one is the failure this
    exists to prevent -- every number derived from `synthetic-v1` means nothing
    about a real child, and the screen has to say so rather than a comment in a
    seed file saying so.
    """
    from seeds.item_bank import WATERMARK

    return WATERMARK
