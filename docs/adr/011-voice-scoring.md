# ADR 011 — Pronunciation scoring: the 0.55 threshold, and three findings

- **Status:** accepted, with one gate open
- **Date:** 2026-08-29
- **Component:** P09 — C08 voice gateway
- **Context docs:** `docs/04d-components-voice.md` §3 · `docs/12` §Δ2 · `docs/09` P09 · `docs/10` T09

## Context

The scorer decides whether a child who tried to say a word is told they said it
right. docs/04d fixes the design — `normalize_ar`, a weighted phoneme
Levenshtein with a named substitution-cost matrix, three verdicts, accept on the
second attempt regardless — and docs/12 §Δ2 confirms none of it depended on the
vendor that was swapped out underneath it.

What docs/04d leaves open is everything about *how* the phonemes are obtained,
and it turns out that gap contains most of the interesting decisions.

## Decisions

### D1 — `g2p()` is authoritative, not `skills.phonemes`

docs/04d's pseudocode compares against `expected.phonemes`. That column exists
and `seeds/curriculum.py` ships it as the literal string
`PLACEHOLDER-NOT-REVIEWED:<code>` — so scoring against it would compare a
child's speech to a placeholder.

`ExpectedWord.phoneme_targets()` therefore derives phonemes from the label via
`g2p()`, and uses the stored column **only** when it is present and not a
placeholder. A reviewed phoneme column supersedes the rule table the moment one
exists, with no code change.

*Consequence:* the quality of every similarity score currently rests on a
hand-written Egyptian Arabic rule table (`domain/g2p.py`) that no phonetician
has read. → REVIEW-QUEUE

### D2 — A single-character phoneme alphabet, not IPA

Emphatics in IPA need a base letter plus a combining mark. Under a naive edit
distance that makes ص→س cost *two* edits rather than the 0.2 docs/04d specifies,
which would silently defeat the most important row in the cost table. The
inventory is therefore one ASCII character per phoneme (`S T D Z $ 3 G 2` and
so on), mnemonic rather than standard.

### D3 — Normalise by the longer string

`similarity = 1 - cost / max(len(expected), len(heard))`. Normalising by the
expected length alone lets a hypothesis of "the target plus five phonemes of
noise" score as a perfect match, because the extra insertions divide away.

### D4 — The threshold stays at 0.55, and calibration is outstanding

docs/04d chose 0.55 deliberately on the permissive side, on an argument about
asymmetric costs: a false accept praises a child for an approximation, which is
what a speech therapist would do; a false reject tells a child who tried that
they were wrong. That argument is sound and the value is unchanged.

**It is still not calibrated.** docs/04d §8 requires a 30-sample recorded set
from real children, via the pilot centre and with consent, before launch. Until
that exists, 0.55 is a design position, not a measurement. → REVIEW-QUEUE

## Findings from the 60-pair corpus

The corpus (`tests/unit/voice_corpus.py`) was written with each row's expected
verdict derived arithmetically from the docs/04d cost table, *before* being run.
Four rows disagreed on the first run. Recording them was more valuable than any
of the rows that agreed.

### F1 — A real false accept at exactly the threshold

باب /bAb/ against شباك /$bAk/ scores **0.550** — one insertion (0.8) plus one
substitution (1.0) over four phonemes. A child asked for "door" who says
"window" was told they were right.

Fixed by a **closed-vocabulary rule**, not by moving the threshold: an ASR
hypothesis that exactly matches *another* taught label is not an approximation
of the target, and the vocabulary is closed at 88 items so we know that with
certainty. The rule caps such a verdict at `retry`; it never raises one.

Raising the threshold instead would have rejected the emphatic and stopping
substitutions the whole design exists to accept, in order to catch a case that
set membership identifies exactly. **This addition is not in docs/04d and has
not been reviewed by a speech-language therapist.** → REVIEW-QUEUE

### F2 — The `vowel length 0.15` class is unreachable

Short vowels are not written in unvowelised Arabic; ASR returns unvowelised
text; `normalize_ar` strips any tashkeel that survives. So a shortened vowel
reaches the scorer as a *deleted long vowel* and is priced at the 0.8 indel, not
at 0.15. The constant is correct and the path to it does not exist until a
reviewed, vowelised phoneme column ships. The corpus rows are renamed
`vowel_shortening` to say what they actually exercise, and the 0.15 cost is
tested directly against explicit phoneme strings instead.

### F3 — Metathesis inside a consonant cluster is cheaper than expected

The hand derivation assumed two 1.0 substitutions. The aligner finds a 1.1 path:
a cluster-internal deletion at 0.3 plus an insertion at 0.8. That follows from
the documented costs and is arguably right — a child reordering a cluster is
still targeting the word — but it is a leniency nobody chose on purpose, and it
is exactly the kind of thing the SLT gate should rule on.

## Also decided

- **Deletion is unconditional and in a `finally`.** There is no path through
  `VoiceService.score_attempt` — not a timeout, not an exception, not a caller
  who forgets — on which a child's audio outlives the request without
  `voice_retention`. Anywhere else it would be a convention.
- **`app.modules.voice` may not import `app.ai`.** Enforced by a test that
  parses every module's imports rather than by spying on gateway calls: a spy
  proves nothing about the code paths a test did not walk.
- **The caregiver override needs no consent and no provider.** It is the path
  that always works, and after docs/12 §3.2 it is also the data-collection
  mechanism for the ASR fine-tune.
- **`bkt_update` gained a `discount_override`.** docs/04d weights an override at
  0.5 of an independent correct and the four-rung ladder has no 0.5. Encoding it
  as `gestural` (0.6) would overstate the evidence and `partial_verbal` (0.35)
  would understate it; both would make the number unfindable later.

## Open

| Gate | Who |
|---|---|
| The 60 (expected, heard) verdicts | Speech-language therapist |
| The closed-vocabulary rule (F1) | Speech-language therapist |
| `g2p` rule table and the tashkeel column | Native Egyptian speaker + phonetician |
| Threshold calibration on 30 real recordings | Pilot centre, with consent |
