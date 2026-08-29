"""The guardrail layers. Pure validation — no I/O, no model calls.

docs/03 §4. Each layer is a separate object because each one fails differently:

    L2 schema        -> repair once, else deterministic fallback
    L3 closed set    -> discard, use the engine's choice, session continues
    L4 numeric       -> repair once, else ship the template report
    L5 clinical      -> BLOCK, escalate to a human, never repair
    L6 conservatism  -> CLAMP to the deterministic value, never raise

The distinction between *reject* and *block* is the important one. A rejection
is invisible: the caller silently uses the deterministic answer and the caregiver
never knows the AI was involved. A block means something was said that must not
reach a family, and a person has to see it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Outcome(StrEnum):
    """Mirrors the guardrail_outcome enum in docs/02 §2."""

    PASS = "pass"  # noqa: S105 -- an outcome name, not a credential
    REPAIRED = "repaired"
    REJECTED_FALLBACK = "rejected_fallback"
    BLOCKED_ESCALATED = "blocked_escalated"


@dataclass(frozen=True, slots=True)
class GuardrailEvent:
    layer: str
    outcome: Outcome
    detail: dict[str, Any] = field(default_factory=dict)


class GuardrailRejection(Exception):
    """The output is unusable. The caller falls back and the user sees nothing."""

    def __init__(self, layer: str, detail: Mapping[str, Any] | None = None) -> None:
        self.layer = layer
        self.detail = dict(detail or {})
        super().__init__(f"guardrail {layer} rejected the output")

    def as_event(self) -> GuardrailEvent:
        return GuardrailEvent(self.layer, Outcome.REJECTED_FALLBACK, self.detail)


class GuardrailBlock(GuardrailRejection):
    """The output is unsafe. Escalate to a human; never repair, never ship."""

    def as_event(self) -> GuardrailEvent:
        return GuardrailEvent(self.layer, Outcome.BLOCKED_ESCALATED, self.detail)


# --- L3: closed-set allow-list ---------------------------------------------


def enforce_candidate_set(chosen_id: str, candidates: Iterable[str]) -> None:
    """The single most important guardrail.

    The AI may reorder a candidate set the engine produced. It may never add to
    it. An out-of-set id means the model invented an item, and an invented
    assessment item is the failure mode this whole architecture exists to make
    impossible.
    """
    allowed = set(candidates)
    if chosen_id not in allowed:
        raise GuardrailRejection("allowlist", {"chosen": chosen_id, "allowed": sorted(allowed)})


def enforce_permutation(chosen: Sequence[str], candidates: Iterable[str]) -> None:
    """A plan must be a permutation of a SUBSET of the candidates.

    Not merely "every element is in the set": a duplicated id would pass that
    check and would show a child the same activity twice in a row.
    """
    allowed = set(candidates)
    extra = [item for item in chosen if item not in allowed]
    if extra:
        raise GuardrailRejection("allowlist", {"unexpected": extra, "allowed": sorted(allowed)})
    if len(set(chosen)) != len(chosen):
        duplicates = sorted({item for item in chosen if list(chosen).count(item) > 1})
        raise GuardrailRejection("allowlist", {"duplicated": duplicates})


def enforce_enum(value: str, allowed: Iterable[str], *, layer: str = "verdict_enum") -> None:
    options = set(allowed)
    if value not in options:
        raise GuardrailRejection(layer, {"value": value, "allowed": sorted(options)})


def enforce_probe_allowlist(probe_id: str, approved: Iterable[str]) -> None:
    """Probes are looked up by id from the item's templates. Never generated."""
    enforce_enum(probe_id, approved, layer="probe_allowlist")


# --- L4: numeric fidelity ---------------------------------------------------

#: Both Western and Eastern Arabic digits.
_DIGITS = re.compile(r"[\d٠-٩]+(?:[.,٫][\d٠-٩]+)?")

_EASTERN_TO_WESTERN = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

#: Small counts appear in ordinary prose ("three activities") and are not
#: claims about the child's development.
_FREELY_ALLOWED = frozenset(str(n) for n in range(11))


def normalise_number(token: str) -> str:
    """Fold Eastern digits and decimal separators to a canonical form.

    `٣٫٥`, `3.5` and `3,5` are the same number, and a narrative that says one
    while the engine computed another must be caught regardless of which script
    the model happened to use.
    """
    western = token.translate(_EASTERN_TO_WESTERN).replace("٫", ".").replace(",", ".")
    try:
        value = float(western)
    except ValueError:
        return western
    if value == int(value):
        return str(int(value))
    return f"{value:g}"


def enforce_numeric_fidelity(narrative: str, engine_numbers: Mapping[str, Any]) -> None:
    """Every digit in the narrative must equal a number the engine computed.

    This is what stops "he is at the level of a 3-year-old" reaching a parent
    when the engine computed 2.5. The model narrates numbers; it never produces
    one.
    """
    allowed = {normalise_number(str(value)) for value in engine_numbers.values()}
    allowed |= _FREELY_ALLOWED
    for token in _DIGITS.findall(narrative):
        if normalise_number(token) not in allowed:
            raise GuardrailRejection(
                "numeric_equality",
                {"token": token, "normalised": normalise_number(token), "allowed": sorted(allowed)},
            )


# --- L5: clinical safety ----------------------------------------------------

#: A cheap deterministic pre-filter. Catches the obvious before a model call,
#: and it FAILS CLOSED — if the classifier errors, the keyword verdict stands.
#:
#: PLACEHOLDER: this list is agent-authored. docs/09 P03 requires the red-team
#: corpus and the blocked-category vocabulary to come from an INDEPENDENT
#: adversary who did not write the prompts. → REVIEW-QUEUE.md #7
BLOCKED_OUTPUT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("diagnosis", re.compile(r"(?i)\b(autism|autistic|adhd|diagnos\w*|syndrome\b)")),
    ("diagnosis", re.compile(r"(توحد|تشخيص|متلازمة)")),
    ("prognosis", re.compile(r"(?i)\b(will (never|always)|prognosis|by age \d)")),
    ("prognosis", re.compile(r"(مش هيقدر|هيفضل|مستقبل\w* هيكون)")),
    ("medication", re.compile(r"(?i)\b(medication|dose|dosage|mg\b|supplement|prescri\w*)")),
    ("medication", re.compile(r"(دوا|جرعة|علاج دوائي|مكمل)")),
    ("therapy_prescription", re.compile(r"(?i)\b(stop (the )?therapy|discontinue|you must see)")),
    ("therapy_prescription", re.compile(r"(بطل العلاج|وقف الجلسات)")),
    ("normal_comparison", re.compile(r"(?i)\b(normal|typical) (child|children|kids)\b")),
    ("normal_comparison", re.compile(r"(أطفال طبيعيين|الأطفال العاديين|زي الأطفال الطبيعية)")),
    (
        "false_hope",
        re.compile(r"(?i)\b(guarantee|will definitely|cure[sd]?\b|completely (fix|heal))"),
    ),
    ("false_hope", re.compile(r"(نضمن|هيتعالج خالص|هيبقى زي أي حد)")),
    ("deficit_framing", re.compile(r"(متأخر|تأخر|عجز|قصور)")),
)

#: Input categories that bypass the AI entirely and go straight to a human.
#: Values are escalation_category enum members from docs/02 §2.
RED_FLAG_PATTERNS: tuple[tuple[str, int, re.Pattern[str]], ...] = (
    ("seizure", 1, re.compile(r"(?i)\b(seizure|convulsion|fit[s]?\b|epilep)")),
    ("seizure", 1, re.compile(r"(تشنج|تشنجات|صرع|رمشة عين وسرحان)")),
    ("feeding_aspiration", 1, re.compile(r"(?i)\b(chok\w*|aspirat\w*|turn(s|ed)? blue)")),
    ("feeding_aspiration", 1, re.compile(r"(بيشرق|شرقان|بيزرق|اختناق)")),
    ("self_harm", 1, re.compile(r"(?i)\b(hurt\w* (him|her)self|head.?bang|self.?harm)")),
    ("self_harm", 1, re.compile(r"(بيضرب نفسه|بيأذي نفسه|بيخبط راسه)")),
    ("safeguarding", 1, re.compile(r"(?i)\b(abuse|neglect|hit\w* (him|her)|not safe)")),
    ("safeguarding", 1, re.compile(r"(بيتضرب|إهمال|مش أمان)")),
    ("regression", 2, re.compile(r"(?i)\b(lost (skills|words)|stopped (talking|walking)|regress)")),
    ("regression", 2, re.compile(r"(بطل يتكلم|نسي الكلام|رجع لورا|فقد مهارات)")),
    (
        "medical_advice_requested",
        3,
        re.compile(r"(?i)\b(should I (give|stop)|is (this|it) (autism|normal)|what medicine)"),
    ),
    ("medical_advice_requested", 3, re.compile(r"(أديله دوا|هو عنده توحد|أوقف العلاج)")),
    ("distress", 2, re.compile(r"(?i)\b(I can'?t (cope|do this)|want to give up|depress)")),
    ("distress", 2, re.compile(r"(مش قادرة|تعبت خلاص|حاسة إني فاشلة|مش عارفة أكمل)")),
)


@dataclass(frozen=True, slots=True)
class SafetyFinding:
    category: str
    severity: int
    excerpt: str


def screen_output(text: str) -> list[SafetyFinding]:
    """Blocked output categories present in model-generated prose."""
    findings: list[SafetyFinding] = []
    for category, pattern in BLOCKED_OUTPUT_PATTERNS:
        match = pattern.search(text)
        if match:
            findings.append(SafetyFinding(category=category, severity=1, excerpt=match.group(0)))
    return findings


def screen_input(text: str) -> list[SafetyFinding]:
    """Red-flag categories in caregiver input. These bypass the AI entirely."""
    findings: list[SafetyFinding] = []
    for category, severity, pattern in RED_FLAG_PATTERNS:
        match = pattern.search(text)
        if match:
            findings.append(
                SafetyFinding(category=category, severity=severity, excerpt=match.group(0))
            )
    return findings


def enforce_clinical_safety(text: str, *, classifier_verdict: str | None = None) -> None:
    """Block prose that must never reach a caregiver.

    `classifier_verdict` is the DP0 model call's answer. **Fails closed**: a
    `None` verdict means the classifier errored, and the keyword pre-filter's
    result stands on its own rather than being waved through.
    """
    findings = screen_output(text)
    if findings:
        raise GuardrailBlock(
            "safety_classifier",
            {
                "categories": sorted({f.category for f in findings}),
                "excerpts": [f.excerpt for f in findings],
                "source": "keyword_prefilter",
            },
        )
    if classifier_verdict is not None and classifier_verdict != "safe":
        raise GuardrailBlock(
            "safety_classifier",
            {"categories": [classifier_verdict], "source": "classifier"},
        )


# --- L6: conservatism -------------------------------------------------------

#: Higher means more permissive. The AI may move down this ladder, never up.
VERDICT_RANK: dict[str, int] = {"withhold": 0, "confirm": 1}


def enforce_conservatism(ai_verdict: str, deterministic: str) -> tuple[str, GuardrailEvent | None]:
    """Clamp an AI verdict down to the deterministic one. Never raises.

    Returns the verdict to use, and an event if a clamp happened. Backed by the
    `ai_cannot_grant` CHECK constraint, so this holds even if this function is
    wrong.
    """
    if ai_verdict not in VERDICT_RANK or deterministic not in VERDICT_RANK:
        # An unrecognised verdict is treated as the most conservative option.
        return "withhold", GuardrailEvent(
            "monotonicity",
            Outcome.REPAIRED,
            {"ai": ai_verdict, "deterministic": deterministic, "reason": "unknown_verdict"},
        )
    if VERDICT_RANK[ai_verdict] > VERDICT_RANK[deterministic]:
        return deterministic, GuardrailEvent(
            "monotonicity",
            Outcome.REPAIRED,
            {"ai": ai_verdict, "deterministic": deterministic},
        )
    return ai_verdict, None


# --- L7-adjacent: PII leak check -------------------------------------------


def enforce_no_pii(payload: Any, identifiers: Sequence[str]) -> None:
    """Nothing from the children table may appear in an outgoing payload."""
    from app.ai.redaction import contains_identifier

    leaked = contains_identifier(payload, identifiers)
    if leaked:
        # The identifiers themselves are NOT put in the detail: that would move
        # the leak from the request into the guardrail_events table.
        raise GuardrailBlock("pii_leak", {"count": len(leaked)})


# --- reading level ----------------------------------------------------------

#: docs/06: caregiver copy is plain. A sentence longer than this is a signal the
#: model has drifted into clinical register.
MAX_SENTENCE_WORDS = 25


def enforce_reading_level(text: str, *, max_words: int = MAX_SENTENCE_WORDS) -> None:
    for sentence in re.split(r"[.!?؟।\n]+", text):
        words = sentence.split()
        if len(words) > max_words:
            raise GuardrailRejection("reading_level", {"words": len(words), "limit": max_words})
