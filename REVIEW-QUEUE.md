# REVIEW-QUEUE

**Read this file first.** Every entry is an open gate that only a person can
close. Each is written to be actionable without reading any transcript.

Nothing here has been closed by the orchestrator, and nothing here will be.

_Last updated: 2026-08-29 · after P01–P08_

---

## Summary

| # | What | Blocks | Who | Effort |
|---|---|---|---|---|
| **1** | Arabic UI strings are placeholders | Stage 5 | Native Egyptian Arabic speaker | part of the ~3 days |
| **2** | Decision O1: Portage licensing | PGEE go-live | You | licensing |
| **3** | Decision O2: the named clinician | **Stage 2 gate** | You, then them | ~2 days of theirs |
| **4** | 6 golden scoring cases are not independently derived | **Stage 2 gate** | Clinician | ~2 hours |
| **5** | The mastery rule needed an unreviewed addition | Stage 3 gate | Clinician + you | ~1 hour to decide |
| **6** | 88 curriculum labels, vowelisation and phonemes | Stage 3, Stage 5 | Native speaker | ~3 days |
| **7** | Red-team corpus and blocked-category vocabulary | Stage 4 gate | Independent red-teamer | ~1 day |

**Most urgent: #3.** It has recruiting lead time and gates everything after
Stage 2. #4 and #5 both need that same person.

---

## #1 — Arabic UI strings are agent-written placeholders

| | |
|---|---|
| **Status** | 🔴 open · 0 days |
| **Blocks** | Stage 5 content sign-off. Does **not** block development. |

**What I built.** `apps/web/src/messages/ar-EG.json`, plus the consent wording
seeded by migration `0003`, plus the session-summary template in
`app/modules/tutor_ai/session.py`. All carry placeholder markers.

**Note the consent text specifically.** It is a legal instrument under Egypt
PDPL 151/2020. It needs a lawyer as well as a native speaker, and changing it
later requires a new version row — a caregiver consented to a specific text.

---

## #2 — Decision O1: Portage Guide licensing

| | |
|---|---|
| **Status** | 🔴 open · 0 days |
| **Blocks** | PGEE **go-live**, not the build. |

The engine works on any bank; it is built and tested against a synthetic
120-item bank watermarked `NOT FOR CLINICAL USE`. The swap only has to be
*possible*, which is why this is worth answering before more AI work lands on
top of it.

---

## #3 — Decision O2: the named clinician

| | |
|---|---|
| **Status** | 🔴 open · 0 days |
| **Blocks** | **Stage 2 gate**, and #4 and #5 below |
| **Effort** | Recruiting time, then ~2 days of theirs spread across the build |

A named developmental paediatrician or early-intervention specialist who will
(a) verify the six hand-calculated scoring cases, (b) sign the item bank and
report template, (c) staff the escalation rota behind the 48-hour promise.

**What happens if you delay.** I keep building. P04 sits finished and
unverified. Nothing after Stage 2 ships.

The escalation copy must be human-written and clinician-reviewed, **never
model-generated**. I have not drafted it and will not.

---

## #4 — The six golden scoring cases are not independently derived

| | |
|---|---|
| **Status** | 🔴 open · 0 days |
| **Blocks** | **Stage 2 gate** |
| **Where** | `services/api/tests/unit/test_assessment_golden.py` |
| **Effort** | ~2 hours with a calculator |

**What to look at.** Six scenarios, one per developmental domain, each with the
full arithmetic written out in the test file — entry band, basal, ceiling, raw
score, the interpolation, and the quotient. You can check them on paper without
reading any code.

**The question to answer.** Does each expected developmental age and quotient
follow from the stated rules? And separately: are the *rules* right — a basal of
8 consecutive passes, a ceiling of 6, half credit for `emerging`?

**Why this is queued rather than closed.** `ORCHESTRATOR.md` §5 requires an
independent oracle: one session writes the engine, a second writes the
expectations from the rules alone, neither sees the other. **That protocol was
not followed** — this session has no sub-session capability enabled, so the same
author produced both.

The weaker substitute actually used: the expectations were derived from the
written rules and written down **before** the engine was implemented, and the
engine then agreed with all six on the first run. That is evidence, not
verification.

**One finding worth your attention.** The scoring pseudocode in `docs/04b §C03`,
read literally, **double-counts every item inside the basal run** —
`raw = below_basal + yes_count` counts the run twice. I implemented the only
coherent reading (recorded in `docs/adr/006-scoring-rules.md`). A clinician
should confirm which reading is intended, because it changes every
developmental age the product reports.

---

## #5 — The mastery rule needed an addition, and nobody has reviewed it

| | |
|---|---|
| **Status** | 🔴 open · 0 days |
| **Blocks** | Stage 3 gate |
| **Where** | `services/api/app/modules/learning/domain/mastery.py` |
| **Effort** | ~1 hour to understand, then a decision |

**The finding.** P07 requires that a random tapper never reaches mastery, and
`ORCHESTRATOR.md` calls that "the real safety net". **The rule as specified in
`docs/04c §C06` does not achieve it.**

Measured: a uniformly random tapper reaches `p_known ≈ 0.999` in **500/500**
simulations, at 2, 3 and 4 choices. The cause is structural. The update ends
with `p_known = posterior + (1 - posterior) × p_transit`, so every opportunity
moves the estimate toward 1 whether the answer was right or wrong. The other
three conditions do not help: a random tapper answering unprompted has an
independent ratio of 1.0 and satisfies the distinct-days and delayed-pass
conditions within a week.

**What I added.** An accuracy-above-chance condition, which random behaviour
cannot satisfy by construction. A fixed margin was not enough and my first
attempt at one was defeated — the rule is re-evaluated after every attempt, so
500 attempts give noise 500 chances to cross any fixed line. The guard is now an
anytime-valid bound (a Hoeffding tail with the confidence divided across the
number of looks) that bounds the probability of a chance-level child ever
satisfying it at 1e-5 **for the whole run**.

Verified at 1000 simulations per choice count: **0/1000** random tappers reach
mastery.

**What I need you to decide.** Two things:

1. **The addition itself is unreviewed.** The confidence level, the window and
   the minimum-attempt floor are engineering judgements, not clinical ones, and
   they decide who is told their child has mastered a skill.

2. **It costs speed at two choices, and that is measured:**

   | choices | 100% accurate | 95% | 85% |
   |---|---|---|---|
   | 2 | 30 attempts | 38 | **74, and only 19/40 ever master** |
   | 3 | 17 | 20 | 26 |
   | 4 | 13 | 13 | 18 |

   At two choices a coin flip is already half right, so separating 85% from
   guessing takes many trials. **`children.max_choices` defaults to 2.** A child
   practising at two choices with realistic accuracy will be slow to be credited.

   The mitigation already in the design is to raise the choice count as skills
   progress (docs/06: "3–4 only for skills already at `practising` or better").
   Someone should confirm that is enough, or change the default.

---

## #6 — 88 curriculum labels: vowelisation, phonemes, distractor pools

| | |
|---|---|
| **Status** | 🔴 open · 0 days |
| **Blocks** | Stage 3 and Stage 5 |
| **Where** | `services/api/seeds/curriculum.py` |
| **Effort** | ~3 days |

**What is real and what is not.** The word lists — 10 colours, 10 body parts, 20
household objects, 10 social phrases, 28 letters, 10 numerals — are transcribed
verbatim from `docs/02 §10.1`. Everything *derived* is a marked placeholder:

- **`label_vowelised` (tashkeel).** Drives TTS. This is the one that matters
  most: wrong tashkeel means Nour mispronounces a word, repeatedly, to a child
  who is learning to speak from her. I deliberately left the bare word rather
  than guessing — a plausible-but-wrong vowelisation would be worse than none,
  because it would ship.
- **`phonemes` (IPA).** Drives the pronunciation similarity scorer.
- **`distractor_pool`.** `docs/04c §C05` requires these to be *hand-curated*.
  Mine are mechanical. The contrast rules at selection time do the real work and
  are tested over every colour pair, but the pools themselves need a person.

`REVIEWED_BY` in that file is empty, and a test asserts it stays empty. When you
sign off, that test gets inverted — that inversion is the deliberate, visible
moment the gate closes.

---

## #7 — Red-team corpus and the blocked-category vocabulary

| | |
|---|---|
| **Status** | 🔴 open · 0 days |
| **Blocks** | Stage 4 gate |
| **Where** | `services/api/app/guardrails/layers.py` |
| **Effort** | ~1 day |
| **Who** | Someone who did **not** write the prompts |

**What I built.** The clinical-safety pre-filter: patterns for diagnosis,
prognosis, medication, therapy prescription, comparison to "normal children",
false hope, and deficit framing — in English and Arabic. Plus red-flag input
detection for the seven escalation categories with severities.

**Why it is queued.** I wrote both the attacks and the defences. That is exactly
the arrangement `ORCHESTRATOR.md` Rule 1 forbids me from signing off. The
vocabulary is also certainly incomplete: I do not know the Egyptian colloquial
phrasings a distressed parent actually uses at 2am, and that is precisely what
the severity-1 categories need to catch.

P03 asks for 60 adversarial cases from an independent author. I have 0 of those.

---

## Not open, for the record

Mechanical and mine to close — all currently green:

- The random-tapper test (0/1000 at every choice count).
- All four CI guard checks, each with a violation fixture *and* a control
  fixture proving it fires correctly.
- 100% branch coverage on every `domain/` package, the guardrails and the gateway.
- The banned-terms lint and the no-physical-CSS rule.
