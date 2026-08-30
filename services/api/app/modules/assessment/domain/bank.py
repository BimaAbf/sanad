"""An in-memory view of one item bank version. Pure; no I/O.

The service loads rows from Postgres and hands them here. The engine never
touches the database, which is what makes 100% branch coverage on `domain/`
achievable without a fixture stack.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from app.modules.assessment.domain.bands import CumulativeRow
from app.modules.assessment.domain.state import Band, ItemRef


@dataclass(frozen=True, slots=True)
class BankItem:
    ref: ItemRef
    #: A `yes` here implies `yes` on these item ids (evidence propagation).
    implies_pass: tuple[str, ...] = ()


@dataclass(slots=True)
class Bank:
    version: str
    bands: tuple[Band, ...]
    _items: dict[str, BankItem] = field(default_factory=dict)
    _by_domain: dict[str, list[BankItem]] = field(default_factory=dict)

    @classmethod
    def build(cls, *, version: str, bands: Iterable[Band], items: Iterable[BankItem]) -> Bank:
        bank = cls(version=version, bands=tuple(sorted(bands, key=lambda b: b.id)))
        for item in items:
            bank._items[item.ref.id] = item
            bank._by_domain.setdefault(item.ref.domain, []).append(item)
        for domain_items in bank._by_domain.values():
            domain_items.sort(key=lambda i: i.ref.ordinal)
        bank._validate()
        return bank

    def _validate(self) -> None:
        """Ordinals must be dense and start at zero, per domain.

        A gap would silently break cursor arithmetic — the engine would walk
        past an ordinal that has no item and conclude the domain is finished.
        """
        for domain, items in self._by_domain.items():
            ordinals = [i.ref.ordinal for i in items]
            if ordinals != list(range(len(items))):
                raise ValueError(f"domain {domain!r} has non-dense ordinals: {ordinals[:10]}")

    # --- lookups -----------------------------------------------------------

    @property
    def domains(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_domain))

    def items_in(self, domain: str) -> Sequence[BankItem]:
        return self._by_domain.get(domain, [])

    def count(self, domain: str) -> int:
        return len(self._by_domain.get(domain, []))

    def max_ordinal(self, domain: str) -> int:
        return self.count(domain) - 1

    def at(self, domain: str, ordinal: int) -> ItemRef | None:
        items = self._by_domain.get(domain, [])
        if 0 <= ordinal < len(items):
            return items[ordinal].ref
        return None

    def ref(self, item_id: str) -> ItemRef:
        return self._items[item_id].ref

    def domain_of(self, item_id: str) -> str:
        return self._items[item_id].ref.domain

    def implies_pass(self, item_id: str) -> tuple[str, ...]:
        item = self._items.get(item_id)
        return item.implies_pass if item else ()

    def has(self, item_id: str) -> bool:
        return item_id in self._items

    def cumulative_by_band(self, domain: str) -> list[CumulativeRow]:
        """(band_id, cumulative_items_through_band, min_months, max_months).

        Bands with no items still appear, carrying the running cumulative
        forward, so `age_equivalent` sees a monotonic sequence.
        """
        counts: dict[int, int] = {}
        for item in self._by_domain.get(domain, []):
            counts[item.ref.band] = counts.get(item.ref.band, 0) + 1
        rows: list[CumulativeRow] = []
        running = 0
        for band in self.bands:
            running += counts.get(band.id, 0)
            rows.append((band.id, running, band.min_months, band.max_months))
        return rows

    @property
    def max_months(self) -> int:
        return max((b.max_months for b in self.bands), default=0)
