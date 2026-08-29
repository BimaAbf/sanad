"""Verdicts. Three of them, and the second attempt is always accepted.

docs/04d §3. The asymmetry is stated there and is worth repeating at the point
of implementation, because it is the thing a future reader will be tempted to
"fix":

    The cost of a false accept is that a child is praised for an approximation —
    which is exactly what a speech therapist would do. The cost of a false
    reject is that a child who tried is told they were wrong. These costs are
    not symmetric.

Pure. No I/O, no provider, no network.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from app.modules.voice.domain.g2p import g2p
from app.modules.voice.domain.normalize import normalize_ar
from app.modules.voice.domain.similarity import phoneme_similarity

#: docs/04d §3. Calibration against real child recordings is outstanding and is
#: recorded in docs/adr/011-voice-scoring.md — this value is a design position,
#: not a measurement.
ACCEPT_THRESHOLD = 0.55
RETRY_THRESHOLD = 0.30

#: After this many attempts the answer is accepted whatever was heard.
ALWAYS_ACCEPT_FROM_ATTEMPT = 2


class Verdict(StrEnum):
    ACCEPT = "accept"
    RETRY = "retry"
    UNCLEAR = "unclear"


class AttemptResult(StrEnum):
    """How the attempt is written to `attempts.result`."""

    CORRECT = "correct"
    ACCEPTED_ON_EFFORT = "accepted_on_effort"
    CAREGIVER_CONFIRMED = "caregiver_confirmed"
    NO_RESPONSE = "no_response"


@dataclass(frozen=True, slots=True)
class Hypothesis:
    text: str
    confidence: float = 0.0


@dataclass(frozen=True, slots=True)
class AsrResult:
    """What a provider returned. `provider` is recorded on the attempt row."""

    n_best: tuple[Hypothesis, ...] = ()
    provider: str = "null"
    #: True when no provider answered at all, as distinct from answering with
    #: nothing. The two lead to different caregiver-facing copy.
    unavailable: bool = False


@dataclass(frozen=True, slots=True)
class ExpectedWord:
    """The target, from the curriculum. Both spellings are matched."""

    skill_code: str
    label_ar: str
    label_egy: str
    #: A reviewed phoneme string, when one exists. Empty means "derive it",
    #: which is the state today because seeds/curriculum.py ships placeholders.
    phonemes: str = ""

    def phoneme_targets(self) -> tuple[str, ...]:
        if self.phonemes and not self.phonemes.startswith("PLACEHOLDER"):
            return (self.phonemes,)
        targets = {g2p(self.label_ar), g2p(self.label_egy)}
        return tuple(sorted(target for target in targets if target))

    def exact_forms(self) -> tuple[str, ...]:
        return tuple(sorted({normalize_ar(self.label_ar), normalize_ar(self.label_egy)}))


@dataclass(frozen=True, slots=True)
class Score:
    verdict: Verdict
    similarity: float
    heard: str
    result: AttemptResult | None
    #: Why the verdict came out the way it did — surfaced in the console, never
    #: to a caregiver and never to a child.
    reason: str = ""
    matched_exactly: bool = False
    guardrail_notes: tuple[str, ...] = field(default_factory=tuple)


def classify(similarity: float) -> Verdict:
    """The three bands. Boundaries are inclusive at the bottom."""
    if similarity >= ACCEPT_THRESHOLD:
        return Verdict.ACCEPT
    if similarity >= RETRY_THRESHOLD:
        return Verdict.RETRY
    return Verdict.UNCLEAR


def is_a_different_taught_word(heard: str, competing: Sequence[str]) -> bool:
    """True when the hypothesis is *exactly* another word the product teaches.

    ================================================================================
    AN ADDITION TO docs/04d §3, AND WHY
    ================================================================================
    The 60-pair corpus found a false accept at the boundary: باب /bAb/ against
    شباك /$bAk/ scores exactly 0.550 — an insertion (0.8) plus one substitution
    (1.0) over a 4-phoneme string — and 0.550 >= the accept threshold. A child
    asked for "door" who says "window" is told they were right.

    Leniency is deliberate in this scorer and must stay. But leniency is about
    *approximations of the target*. شباك is not an approximation of باب; it is a
    different word, and we know that with certainty because the vocabulary is
    closed at 88 items. So: an exact match against another taught label caps the
    verdict at `retry`. It never raises a verdict, only lowers one.

    Tightening the 0.55 threshold instead would have been the wrong fix — it
    would reject the emphatic and stopping substitutions that the whole design
    exists to accept, in order to catch a case that closed-set membership
    identifies exactly.

    **This addition has not been reviewed by a speech-language therapist.**
    → REVIEW-QUEUE.md
    ================================================================================
    """
    normalised = normalize_ar(heard)
    if not normalised:
        return False
    return any(normalised == normalize_ar(word) for word in competing)


def best_similarity(expected: ExpectedWord, asr: AsrResult) -> tuple[float, str, bool]:
    """Best (similarity, heard, exact) across every hypothesis.

    Any hypothesis may match — n-best exists precisely because the top
    hypothesis of a recogniser that was never trained on this population is a
    weak signal, and discarding the rest would throw away the reason we asked
    for five.
    """
    exact_forms = expected.exact_forms()
    targets = expected.phoneme_targets()

    best = 0.0
    heard = ""
    for hypothesis in asr.n_best:
        normalised = normalize_ar(hypothesis.text)
        if normalised and normalised in exact_forms:
            return 1.0, hypothesis.text, True
        if not targets:  # pragma: no cover - a skill with no label cannot ship
            continue
        similarity = max(phoneme_similarity(target, g2p(normalised)) for target in targets)
        if similarity > best or not heard:
            best = max(best, similarity)
            heard = hypothesis.text
    return best, heard, False


def score_attempt(
    expected: ExpectedWord,
    asr: AsrResult,
    *,
    attempt_no: int,
    competing_labels: Sequence[str] = (),
) -> Score:
    """The whole scoring decision, including accept-on-effort.

    `attempt_no >= 2` short-circuits to accept **before** anything else is
    considered, so a provider outage, silence, or pure noise on the second try
    all end the same way: the child is told they were heard.
    """
    similarity, heard, exact = best_similarity(expected, asr)

    if attempt_no >= ALWAYS_ACCEPT_FROM_ATTEMPT:
        return Score(
            verdict=Verdict.ACCEPT,
            similarity=similarity,
            heard=heard,
            result=AttemptResult.CORRECT if exact else AttemptResult.ACCEPTED_ON_EFFORT,
            reason="accepted_on_effort" if not exact else "exact_match",
            matched_exactly=exact,
        )

    if asr.unavailable:
        # Not a judgement about the child. The caller switches the activity into
        # caregiver-confirmation mode rather than showing anything to the child.
        return Score(
            verdict=Verdict.UNCLEAR,
            similarity=0.0,
            heard="",
            result=None,
            reason="asr_unavailable",
        )

    verdict = classify(similarity)
    notes: tuple[str, ...] = ()
    if (
        verdict is Verdict.ACCEPT
        and not exact
        and is_a_different_taught_word(heard, competing_labels)
    ):
        # Lowered, never raised. See `is_a_different_taught_word`.
        verdict = Verdict.RETRY
        notes = ("competing_taught_word",)

    return Score(
        verdict=verdict,
        similarity=similarity,
        heard=heard,
        # retry and unclear write no attempt row at all: the child has not
        # finished answering yet, and recording a failure they are about to
        # correct would corrupt the measurement in the pessimistic direction.
        result=AttemptResult.CORRECT if verdict is Verdict.ACCEPT else None,
        reason="exact_match" if exact else f"similarity={similarity:.3f}",
        matched_exactly=exact,
        guardrail_notes=notes,
    )


def caregiver_override() -> Score:
    """The caregiver tapped "قالها صح ✅"."""
    return Score(
        verdict=Verdict.ACCEPT,
        similarity=1.0,
        heard="",
        result=AttemptResult.CAREGIVER_CONFIRMED,
        reason="caregiver_override",
    )
