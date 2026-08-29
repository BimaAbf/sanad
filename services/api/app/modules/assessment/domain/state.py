"""Frozen state for the assessment engine. Pure data, no behaviour, no I/O.

Everything the engine needs to decide what to ask next and what to score lives
in `AssessmentState`. Nothing is mutated: `record()` returns a new state. That
is what makes replay-after-correction exact rather than approximately right.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum


class Verdict(StrEnum):
    """Mirrors the response_verdict enum in docs/02 §2."""

    YES = "yes"
    EMERGING = "emerging"
    NO = "no"
    NOT_APPLICABLE = "not_applicable"
    SKIPPED = "skipped"


#: A pass for run-detection purposes. `emerging` is deliberately NOT here: it is
#: the conservative reading in docs/04b §C03, and it stops a run of "sort of"
#: answers inflating a ceiling.
PASSING: frozenset[Verdict] = frozenset({Verdict.YES})

#: Excluded from both runs and from scoring entirely — a motor item for a child
#: who uses a wheelchair is not a failure, it is not applicable.
EXCLUDED_FROM_RUNS: frozenset[Verdict] = frozenset({Verdict.NOT_APPLICABLE})

#: Breaks a consecutive run without contributing to it: the run restarts.
BREAKS_RUN: frozenset[Verdict] = frozenset({Verdict.SKIPPED})


@dataclass(frozen=True, slots=True)
class Rules:
    """Administration constants. Data, not code — a licensed manual may differ.

    Defaults are the assessment_rules defaults from docs/02 §4. They are
    UNVERIFIED against any published manual; see docs/adr/006-scoring-rules.md.
    """

    basal_consecutive: int = 8
    ceiling_consecutive: int = 6
    entry_band_offset: int = -1
    emerging_credit: float = 0.50
    max_probes_per_item: int = 2
    min_days_between: int = 150
    scatter_credit_mult: float = 0.50


@dataclass(frozen=True, slots=True)
class ItemRef:
    id: str
    domain: str
    band: int
    sequence: int
    #: Global position within the domain, across bands. The engine works
    #: entirely in ordinals; bands only matter for scoring.
    ordinal: int


@dataclass(frozen=True, slots=True)
class Band:
    id: int
    label: str
    min_months: int
    max_months: int


@dataclass(frozen=True, slots=True)
class DomainState:
    domain: str
    entry_band: int
    entry_ordinal: int
    answered: Mapping[str, Verdict] = field(default_factory=dict)
    #: Highest ordinal of the confirmed basal run. Items strictly below it are
    #: credited as passes without being asked.
    basal_ordinal: int | None = None
    ceiling_ordinal: int | None = None
    cursor_up: int = 0
    cursor_down: int = 0
    complete: bool = False
    #: True when the bank floor was reached without a basal run ever forming.
    basal_assumed: bool = False


@dataclass(frozen=True, slots=True)
class AssessmentState:
    #: Corrected age. Entry bands use corrected; the report shows both.
    child_months: float
    bank_version: str
    rules: Rules
    domains: Mapping[str, DomainState]
    #: The child's age is outside the bank's range; DQ is suppressed entirely.
    out_of_range: bool = False


@dataclass(frozen=True, slots=True)
class DomainScore:
    domain: str
    items_administered: int
    passes: int
    emerging: int
    fails: int
    not_applicable: int
    basal_band: int | None
    ceiling_band: int | None
    raw: float
    developmental_age_months: float
    developmental_quotient: float
    #: DQ is meaningless and must not be displayed when this is set: either the
    #: child's age is 0, or their age is outside the bank's range.
    dq_suppressed: bool = False
    #: DQ above 200 is almost always a data error rather than a real finding.
    dq_warning: bool = False
    delta_da_months: float | None = None


@dataclass(frozen=True, slots=True)
class Answer:
    """One recorded answer, in administration order. The replay input."""

    item_id: str
    verdict: Verdict
    propagated: bool = False


def domain_states(
    domains: Sequence[str], entry: Mapping[str, tuple[int, int]]
) -> dict[str, DomainState]:
    """Build the initial per-domain state from entry (band, ordinal) pairs."""
    return {
        code: DomainState(
            domain=code,
            entry_band=entry[code][0],
            entry_ordinal=entry[code][1],
            cursor_up=entry[code][1],
            cursor_down=entry[code][1],
        )
        for code in domains
    }
