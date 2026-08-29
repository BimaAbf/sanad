"""Everything the product can say, enumerated.

docs/02 §10.4 and docs/12 §Δ2. After the stack revision this is not a cache
warm-up — it is the **entire** audio surface of the product. There is no runtime
TTS in the child's path at all, so an utterance missing from this list is an
utterance the child will never hear, and publishing with a gap is a defect that
reaches a child as silence.

Hence: this enumeration is the publish gate. `missing_assets()` is what blocks a
release.

Pure. No I/O — the renderer supplies what it managed to produce.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.modules.voice.domain.ssml import DEFAULT_RATE_PCT, Utterance, build_ssml, cache_key


@dataclass(frozen=True, slots=True)
class SkillSpec:
    """The subset of a curriculum skill the renderer needs."""

    code: str
    label_vowelised: str
    label_egy: str
    difficulty_tier: int


@dataclass(frozen=True, slots=True)
class TemplateSpec:
    code: str
    instruction_ar: str
    min_tier: int


@dataclass(frozen=True, slots=True)
class RenderedAsset:
    key: str
    content_hash: str
    url: str
    lufs: float
    duration_ms: int


def _utterance(key: str, text: str, kind: str, *, emphasis: str = "") -> Utterance:
    return Utterance(
        key=key,
        text_vowelised=text,
        emphasis=emphasis,
        kind=kind,
        rate_pct=DEFAULT_RATE_PCT,
    )


def skill_utterances(skills: Sequence[SkillSpec]) -> list[Utterance]:
    """The 88 labels, said on their own.

    The colloquial form is rendered as a separate clip when it differs from the
    written label: the child hears جزمة at home, and a clip that says the MSA
    form teaches a word their family does not use.
    """
    out: list[Utterance] = []
    for skill in skills:
        out.append(_utterance(f"skill:{skill.code}", skill.label_vowelised, "skill"))
        if skill.label_egy and skill.label_egy != skill.label_vowelised:
            out.append(_utterance(f"skill_egy:{skill.code}", skill.label_egy, "skill"))
    return out


def instruction_utterances(
    skills: Sequence[SkillSpec], templates: Sequence[TemplateSpec]
) -> list[Utterance]:
    """Each instruction, with each skill substituted in.

    Deduplicated on the rendered *text*, not on the template code — three
    templates share "وريني {label}" and rendering it three times would waste a
    third of the corpus on identical audio. A template is skipped for a skill
    below its `min_tier`, because that pairing can never be shown.
    """
    seen: set[str] = set()
    out: list[Utterance] = []
    for template in templates:
        for skill in skills:
            if skill.difficulty_tier < template.min_tier:
                continue
            label = skill.label_egy or skill.label_vowelised
            text = template.instruction_ar.replace("{label}", label)
            if text in seen:
                continue
            seen.add(text)
            out.append(
                _utterance(
                    f"instruction:{template.code}:{skill.code}",
                    text,
                    "instruction",
                    emphasis=label,
                )
            )
    return out


def feedback_utterances(success: Sequence[str], retry: Sequence[str]) -> list[Utterance]:
    out: list[Utterance] = []
    for index, line in enumerate(success):
        out.append(_utterance(f"feedback:success:{index}", line, "feedback"))
    for index, line in enumerate(retry):
        out.append(_utterance(f"feedback:retry:{index}", line, "feedback"))
    return out


def item_prompt_utterances(prompts: Iterable[tuple[str, str]]) -> list[Utterance]:
    """(item_id, prompt_ar) for every PGEE item."""
    return [_utterance(f"pgee_item:{item_id}", text, "pgee_item") for item_id, text in prompts]


def ui_utterances(lines: Iterable[tuple[str, str]]) -> list[Utterance]:
    """(key, text) for every fixed UI line — loading, closing, transitions."""
    return [_utterance(f"ui:{key}", text, "ui") for key, text in lines]


def build_inventory(
    *,
    skills: Sequence[SkillSpec],
    templates: Sequence[TemplateSpec],
    success_lines: Sequence[str],
    retry_lines: Sequence[str],
    item_prompts: Iterable[tuple[str, str]],
    ui_lines: Iterable[tuple[str, str]],
) -> list[Utterance]:
    """The whole corpus, in a stable order so a diff between runs is readable."""
    return [
        *skill_utterances(skills),
        *instruction_utterances(skills, templates),
        *feedback_utterances(success_lines, retry_lines),
        *item_prompt_utterances(item_prompts),
        *ui_utterances(ui_lines),
    ]


def content_hashes(inventory: Sequence[Utterance]) -> dict[str, str]:
    """key → cache key. Re-rendering is driven entirely off a change here."""
    return {
        utterance.key: cache_key(utterance, build_ssml(utterance, require_vowelised=False))
        for utterance in inventory
    }


def missing_assets(inventory: Sequence[Utterance], rendered: dict[str, RenderedAsset]) -> list[str]:
    """Keys with no asset, or whose content hash has moved. Empty means publishable."""
    expected = content_hashes(inventory)
    missing: list[str] = []
    for key, digest in expected.items():
        asset = rendered.get(key)
        if asset is None:
            missing.append(f"{key}:absent")
        elif asset.content_hash != digest:
            missing.append(f"{key}:stale")
        elif not asset.url:
            missing.append(f"{key}:no_url")
    return missing


def unvowelised_keys(inventory: Sequence[Utterance]) -> list[str]:
    """Every item that would be mispronounced because it carries no tashkeel.

    Reported as a list rather than raised on the first hit, so one pass tells a
    reviewer the whole scope of the problem. Today this is all 88 skills, because
    `seeds/curriculum.py` ships `label_vowelised` as an explicit placeholder.
    """
    from app.modules.voice.domain.ssml import needs_vowelisation

    return [item.key for item in inventory if needs_vowelisation(item.text_vowelised)]
