"""What to render, what to skip, and what blocks a publish.

Idempotency is by content hash, so a re-render costs only what actually changed.
That is the property that makes the $0.70 figure in docs/12 §3.1 true a second
time: fixing the tashkeel on four words is a four-clip render, not 850.

Pure. The GPU work lives in `renderer.py`; nothing here imports a model.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.voice.domain.inventory import RenderedAsset, content_hashes
from app.modules.voice.domain.ssml import (
    LUFS_TOLERANCE,
    TARGET_LUFS,
    Utterance,
    build_ssml,
    needs_vowelisation,
)

#: docs/12 §Δ2 acceptance: the full corpus renders in under 3 GPU-hours.
BUDGET_GPU_HOURS = 3.0
#: Thunder Compute A6000, verified in docs/12 §3.3.
GPU_USD_PER_HOUR = 0.35
BUDGET_USD = 2.0


@dataclass(frozen=True, slots=True)
class RenderItem:
    key: str
    ssml: str
    content_hash: str
    voice: str
    kind: str


@dataclass(frozen=True, slots=True)
class RenderPlan:
    to_render: tuple[RenderItem, ...]
    unchanged: tuple[str, ...]
    #: Keys present in the store that the inventory no longer contains. Listed,
    #: never auto-deleted: an orphan costs 40 KB, and a delete that turns out to
    #: be wrong costs a re-render and a child hearing silence in between.
    orphans: tuple[str, ...]
    #: Items whose text carries no diacritics. Rendering these would teach a
    #: mispronounced word, so they are a hard stop rather than a warning.
    unvowelised: tuple[str, ...]

    @property
    def is_clean(self) -> bool:
        return not self.unvowelised

    def estimated_gpu_hours(self, seconds_per_item: float = 8.0) -> float:
        return len(self.to_render) * seconds_per_item / 3600.0

    def estimated_usd(self, seconds_per_item: float = 8.0) -> float:
        return self.estimated_gpu_hours(seconds_per_item) * GPU_USD_PER_HOUR


def build_plan(
    inventory: Sequence[Utterance], rendered: dict[str, RenderedAsset]
) -> RenderPlan:
    """Diff the inventory against what R2 already holds."""
    hashes = content_hashes(inventory)
    to_render: list[RenderItem] = []
    unchanged: list[str] = []

    for utterance in inventory:
        digest = hashes[utterance.key]
        existing = rendered.get(utterance.key)
        if existing is not None and existing.content_hash == digest and existing.url:
            unchanged.append(utterance.key)
            continue
        to_render.append(
            RenderItem(
                key=utterance.key,
                ssml=build_ssml(utterance, require_vowelised=False),
                content_hash=digest,
                voice=utterance.voice,
                kind=utterance.kind,
            )
        )

    inventory_keys = {utterance.key for utterance in inventory}
    orphans = sorted(key for key in rendered if key not in inventory_keys)
    unvowelised = tuple(
        utterance.key for utterance in inventory if needs_vowelisation(utterance.text_vowelised)
    )

    return RenderPlan(
        to_render=tuple(to_render),
        unchanged=tuple(unchanged),
        orphans=tuple(orphans),
        unvowelised=unvowelised,
    )


def loudness_outliers(rendered: dict[str, RenderedAsset]) -> list[tuple[str, float]]:
    """Every clip outside -16 ±1 LUFS.

    docs/04d §2 gives the reason, and it is not audio-engineering fussiness: a
    clip that is louder than the ones around it is startling, and a startled
    child stops playing.
    """
    return sorted(
        (key, asset.lufs)
        for key, asset in rendered.items()
        if abs(asset.lufs - TARGET_LUFS) > LUFS_TOLERANCE
    )


def publish_blockers(
    inventory: Sequence[Utterance], rendered: dict[str, RenderedAsset]
) -> list[str]:
    """Everything that must be fixed before content can be published.

    One list, in severity order, because a publish gate that reports the first
    problem only makes the operator run it five times.
    """
    blockers: list[str] = []
    plan = build_plan(inventory, rendered)

    blockers.extend(f"unvowelised:{key}" for key in plan.unvowelised)
    blockers.extend(f"unrendered:{item.key}" for item in plan.to_render)
    blockers.extend(f"loudness:{key}={lufs:.1f}LUFS" for key, lufs in loudness_outliers(rendered))
    return blockers
