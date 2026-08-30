"""Synthetic PGEE item bank generator.

================================================================================
PLACEHOLDER — NOT FOR CLINICAL USE
================================================================================
Every item below is machine-generated scaffolding. The Arabic is templated, the
criteria are invented, and the band placement encodes no developmental evidence
whatsoever. Its ONLY purpose is to let the engine be built and tested against a
bank with the right shape.

It must not be shown to a caregiver, and no number derived from it means
anything about a real child. Replacement is open decision O1 (licensed Portage,
or an original bank authored with a clinician). See REVIEW-QUEUE.md.
================================================================================

Shape: 6 domains x 20 items = 120 items, spread over 6 bands as
[4, 4, 3, 3, 3, 3], giving these cumulative counts per domain:

    band 0 (0-12m):   4    band 3 (36-48m):  14
    band 1 (12-24m):  8    band 4 (48-60m):  17
    band 2 (24-36m): 11    band 5 (60-72m):  20

The distribution is deliberately uniform across domains so the golden cases can
be hand-computed. A real bank will not be uniform.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.assessment.domain.bank import Bank

BANK_VERSION = "synthetic-v1"

WATERMARK = "PLACEHOLDER — NOT FOR CLINICAL USE"

DOMAINS: tuple[tuple[str, str, str, int], ...] = (
    ("infant_stim", "التنبيه المبكر", "Infant stimulation", 1),
    ("socialization", "التواصل الاجتماعي", "Socialisation", 2),
    ("language", "اللغة", "Language", 3),
    ("self_help", "الاعتماد على النفس", "Self-help", 4),
    ("cognitive", "الإدراك", "Cognitive", 5),
    ("motor", "الحركة", "Motor", 6),
)

#: (band_id, label, min_months, max_months)
BANDS: tuple[tuple[int, str, int, int], ...] = (
    (0, "0-1", 0, 12),
    (1, "1-2", 12, 24),
    (2, "2-3", 24, 36),
    (3, "3-4", 36, 48),
    (4, "4-5", 48, 60),
    (5, "5-6", 60, 72),
)

#: Items per band, per domain. Sums to 20.
ITEMS_PER_BAND: tuple[int, ...] = (4, 4, 3, 3, 3, 3)

ITEMS_PER_DOMAIN = sum(ITEMS_PER_BAND)


@dataclass(frozen=True, slots=True)
class SyntheticItem:
    id: str
    bank_version: str
    external_ref: str
    domain_code: str
    band_id: int
    sequence: int
    ordinal: int
    prompt_ar: str
    prompt_ar_msa: str
    example_ar: str
    criterion_ar: str
    observable_cue: str
    implies_pass: tuple[str, ...]
    probe_ids: tuple[str, ...]


def item_id(domain: str, ordinal: int) -> str:
    """Deterministic, readable ids so a golden test can name an item directly."""
    return f"{BANK_VERSION}:{domain}:{ordinal:02d}"


def band_of_ordinal(ordinal: int) -> tuple[int, int]:
    """(band_id, sequence_within_band) for a domain-local ordinal."""
    remaining = ordinal
    for band_id, count in enumerate(ITEMS_PER_BAND):
        if remaining < count:
            return band_id, remaining + 1
        remaining -= count
    raise ValueError(f"ordinal {ordinal} is outside the bank")


def build_items() -> list[SyntheticItem]:
    """Generate the whole bank. Deterministic: no randomness anywhere."""
    items: list[SyntheticItem] = []
    for domain_code, name_ar, _name_en, _sort in DOMAINS:
        for ordinal in range(ITEMS_PER_DOMAIN):
            band_id, sequence = band_of_ordinal(ordinal)
            # Evidence propagation: passing an item implies the one two
            # positions below it in the same domain. A synthetic stand-in for a
            # real prerequisite graph, deliberately sparse so it exercises the
            # traversal without dominating the item count.
            implies = (item_id(domain_code, ordinal - 2),) if ordinal >= 2 else ()
            items.append(
                SyntheticItem(
                    id=item_id(domain_code, ordinal),
                    bank_version=BANK_VERSION,
                    external_ref=f"SYN-{domain_code[:3].upper()}-{ordinal:02d}",
                    domain_code=domain_code,
                    band_id=band_id,
                    sequence=sequence,
                    ordinal=ordinal,
                    prompt_ar=f"[{WATERMARK}] مهارة {name_ar} رقم {ordinal + 1}؟",
                    prompt_ar_msa=f"[{WATERMARK}] مهارة {name_ar} رقم {ordinal + 1}؟",
                    example_ar=f"[{WATERMARK}] مثال توضيحي {ordinal + 1}",
                    criterion_ar=f"[{WATERMARK}] معيار النجاح {ordinal + 1}",
                    observable_cue=(
                        f"PLACEHOLDER observable cue for {domain_code} ordinal {ordinal}"
                    ),
                    implies_pass=implies,
                    probe_ids=(
                        f"{domain_code}:{ordinal:02d}:probe1",
                        f"{domain_code}:{ordinal:02d}:probe2",
                    ),
                )
            )
    return items


def cumulative_by_band() -> list[tuple[int, int, int, int]]:
    """(band_id, cumulative_items, min_months, max_months) — same for every domain."""
    rows: list[tuple[int, int, int, int]] = []
    running = 0
    for (band_id, _label, lo, hi), count in zip(BANDS, ITEMS_PER_BAND, strict=True):
        running += count
        rows.append((band_id, running, lo, hi))
    return rows


def build_bank() -> Bank:
    """The synthetic bank as an in-memory Bank, ready for the engine."""
    from app.modules.assessment.domain.bank import Bank, BankItem
    from app.modules.assessment.domain.state import Band, ItemRef

    return Bank.build(
        version=BANK_VERSION,
        bands=[Band(id=b, label=label, min_months=lo, max_months=hi) for b, label, lo, hi in BANDS],
        items=[
            BankItem(
                ref=ItemRef(
                    id=item.id,
                    domain=item.domain_code,
                    band=item.band_id,
                    sequence=item.sequence,
                    ordinal=item.ordinal,
                ),
                implies_pass=item.implies_pass,
            )
            for item in build_items()
        ],
    )
