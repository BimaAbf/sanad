# REVIEW-QUEUE

**Read this file first.** Every entry is an open gate that only a person can
close. Each is written to be actionable without reading any transcript.

Nothing here has been closed by the orchestrator, and nothing here will be.

_Last updated: 2026-08-29 · after P09–P15_

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
| **8** | 60 pronunciation-scoring verdicts, and **two** additions to the scorer | Stage 5 | Speech-language therapist | ~half a day |
| **9** | The 0.55 acceptance threshold is uncalibrated | Voice go-live | Pilot centre, with consent | 30 recordings |
| **10** | The Nour voice: casting, recording, a perpetual licence | **Stage 5, long lead time** | You | weeks |
| **11** | VoxCPM2 Arabic listening test | Stage 5 voice gate | Native Egyptian speaker | ~half a day |
| **12** | OT accessibility review and real-device audio | **Stage 5 gate** | Occupational therapist + 2 families | ~2 days |
| **13** | Groq DPA and data terms; VoxCPM2 / Qwen licences | **Pilot traffic** | You / legal | days |

**Most urgent: #3 and #10.** #3 has recruiting lead time and gates everything
after Stage 2; #4 and #5 need that same person. #10 is on the critical path for
the entire voice tier and has the longest lead time of anything in this file —
docs/12 §Δ6 puts it in Week 2 for exactly that reason, and it has not started.

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

---

## #8 — The 60 pronunciation-scoring verdicts, and one addition to the scorer

| | |
|---|---|
| **Status** | 🔴 open · 0 days |
| **Blocks** | Stage 5 voice sign-off. Does **not** block development. |
| **Who** | A speech-language therapist working with Egyptian Arabic-speaking children |

**What I built.** `services/api/tests/unit/voice_corpus.py` — 62 (expected,
heard) pairs covering every substitution class in docs/04d §3, each with the
phonological process named and the arithmetic shown.
`docs/adr/011-voice-scoring.md` records what happened when they were run.

**What I need you to answer.** Three questions, and only you can answer them:

1. Are these really the error patterns this population produces?
2. For each accepted row: should a child producing that be told they were right?
3. Are the ten non-matches really non-matches, to a listener?

**One addition needs your ruling specifically.** The corpus found a false accept
at exactly the threshold: باب (door) heard as شباك (window) scores 0.550, and
0.550 is an accept. I did not move the threshold — that would reject the
emphatic and stopping substitutions the whole design exists to accept. Instead I
added a rule: **an ASR hypothesis that exactly matches another taught word is
capped at `retry`.** The vocabulary is closed at 88 items, so we know with
certainty that it is a different word rather than an approximation of the target.

That rule is not in docs/04d. It is mine, and it changes what a child is told.

**A second addition, and it needs the same ruling.** The `vowel length 0.15`
cost in docs/04d was unreachable in practice: unvowelised Arabic writes no short
vowels, so a shortened vowel arrives at the scorer as a *deleted long vowel*,
which was priced at 0.8 — 5.3x what the document sets for the one class it calls
"almost never meaningful". Stacked with one other expected process it pushed a
child out of the accept band: راس /rAs/ produced as /rt/ (vowel shortened, final
/s/ stopped) scored 0.633, a `retry`, where the documented costs give 0.850.

`similarity.deletion_cost` now prices a long vowel deleted **between two
consonants** at 0.15 — CVC → CC, which is what shortening looks like in an
unvowelised transcript. Two restrictions, both established by running the
corpus:

* only between consonants — a long vowel deleted at a word edge changes the
  shape of the word, and stays at 0.8;
* deletion only, never insertion — a cheap *inserted* long vowel lets the
  aligner slide unrelated strings together, and measurably does: صابونة against
  ترابيزة rises from 0.464 to 0.557 and a genuine non-match crosses the accept
  threshold.

The six `vowel_shortening` corpus rows move from 0.73–0.87 to 0.95–0.98. No
non-match row changes band. **Like the closed-vocabulary rule above, this is
mine and it changes what a child is told.** Question 2 applies to it: should a
child who shortens the vowel of a word they otherwise said correctly be told
they were right?

**What happens if this stays open.** The scorer ships with verdicts nobody
clinically qualified has agreed to. Given accept-on-effort the worst case for
the child is being praised for an approximation — but the *measurement* recorded
against them is then wrong, and that measurement is what the caregiver dashboard
is built out of.

---

## #9 — The 0.55 acceptance threshold has never been calibrated

| | |
|---|---|
| **Status** | 🔴 open · 0 days |
| **Blocks** | Voice go-live |
| **Who** | The pilot centre, with consent — then the therapist from #8 reads the result |

docs/04d §8 requires "a 30-sample recorded set from real children (with consent,
via the pilot centre)" to calibrate 0.55 before launch. It does not exist. The
value is a design position argued from asymmetric costs, and the argument is a
good one — but it is an argument, not a measurement, and it decides what a child
is told about their own speech.

Recorded in `docs/adr/011-voice-scoring.md` D4.

---

## #10 — The Nour voice: casting, recording, and a perpetual licence

| | |
|---|---|
| **Status** | 🔴 open · 0 days |
| **Blocks** | **The entire voice tier.** Longest lead time in this file. |
| **Who** | You |

docs/12 §3.1 needs 20–30 minutes of studio-quality recording from a real
Egyptian woman — ideally an early-intervention specialist, or a mother who
naturally speaks to small children — to clone into the Nour voice.

**Step-by-step: [`docs/setup/01-nour-voice.md`](docs/setup/01-nour-voice.md).**
`just voice-script` now generates the document you hand the studio, from the
repo's own curriculum, with a phonetic-coverage check. It carries a DO-NOT-RECORD
banner until #6 closes, because the labels' vowelisation is still mechanical.

**Three things, and the third is a contract.**

1. **Cast and record.** docs/12 §Δ6 puts this in Week 2 precisely because of the
   lead time. Nothing has started.
2. **Render.** About $0.70 of GPU time once the recording exists; the pipeline
   is written (`tools/voice_render/`).
3. **A signed release.** The person whose voice becomes Nour signs a perpetual,
   transferable licence for synthetic reproduction. A real contract, not a
   formality: you are cloning someone's voice and shipping it to thousands of
   children, and assumption C7 then says that voice must never change.

**What happens if this stays open.** There is no audio at all. The child app
plays static files from a CDN; the CDN is empty; no session can run.

---

## #11 — VoxCPM2 Arabic listening test

| | |
|---|---|
| **Status** | 🔴 open · 0 days |
| **Blocks** | The Stage 5 voice gate — this decides the whole TTS choice |
| **Who** | A native Egyptian Arabic speaker |

docs/12 §Δ2 makes this an explicit gate: render 20 of our actual skill labels
with VoxCPM2 and blind-rate them against the Azure equivalents. **If VoxCPM2
loses on intelligibility or dialect authenticity, keep Azure for TTS and take
the rest of the revision.**

Include the labels that expose dialect. جزمة must be /gazma/, not /dʒazma/;
جبنة must be /gebna/. A child taught /dʒazma/ learns a word they will not hear
at home and that their family will not recognise — which breaks the one thing
the whole product rests on: a child mapping a sound to an object in their own
house.

Half a day, and it decides the voice tier.

---

## #12 — Occupational therapist accessibility review, and real-device audio

| | |
|---|---|
| **Status** | 🔴 open · 0 days |
| **Blocks** | **Stage 5 gate** |
| **Who** | An occupational therapist, plus two families |

**What I built.** Every mechanical rule from docs/04e §C13 and docs/06 §4 is now
a constant with a test against it: 88px targets, 5-word instructions, the 3Hz
animation ceiling, the 400ms tap tolerance, 800ms of calm between activities,
the retuned VAD parameters. 87 web tests pass.

**Why that is not enough, in the document's own words:** *"axe-core cannot tell
you that an 8-second wait is too short for a particular child. A parent can."*

**Two specific things I could not do.**

1. **Real-device audio.** docs/10 T13 §23 requires iOS Safari on hardware, not
   an emulator — the autoplay policy is exactly what emulators get wrong. The
   spec is `test.skip` with the reason written into it. One low-end Android and
   one iOS device are needed.
2. **A document disagreement I resolved on my own authority.** docs/04e §C13
   says touch targets are ≥ 80px; docs/06 §5 and docs/09 P13 say ≥ 88px. I used
   88, because the stricter value cannot violate either. Worth one sentence of
   confirmation from you.

---

## #13 — Groq data terms, and two model licences

| | |
|---|---|
| **Status** | 🔴 open · 0 days |
| **Blocks** | **Any pilot traffic**, including pseudonymised. Not development. |
| **Who** | You, and probably a lawyer |

**Step-by-step: [`docs/setup/02-groq-and-model-licences.md`](docs/setup/02-groq-and-model-licences.md).**

docs/12 §2 is unambiguous: *"Groq's free-tier data terms are not established…
Before any pilot traffic — even pseudonymised — someone must read those and
confirm: no training on our data, a stated retention period, and a signed DPA.
This is child health-adjacent data in a PDPL jurisdiction."*

Two more, from docs/12 §3.4, both load-bearing:

- **VoxCPM2** weights — commercial-use terms, and whether a voice cloned from a
  consented recording carries any restriction.
- **Qwen3-ASR-1.7B** — commercial use, and distribution of a fine-tuned
  derivative. The fine-tune is the strategic argument in docs/12 §3.2; if the
  licence forbids it, that argument collapses.

---

## #14 — The child app's pictures, its 25 invented letter keywords, and four manifest fields

| | |
|---|---|
| **Status** | 🔴 open · 0 days |
| **Blocks** | Stage 3 (any family sees `/play`) |
| **Where** | `apps/web/src/content/curriculum.ts`, `apps/web/src/components/art/objects.tsx`, `apps/web/src/lib/manifest.ts` |
| **Effort** | ~2 days, plus one session with children |

`/play` used to be one hard-coded activity pointing at two `.svg` files that did
not exist. It is now the five `activity_kind` values, drawing 56 illustrations
from the 88-skill curriculum. Three parts of that need a person.

**1. Fifty-six drawings nobody has shown to a child.** They are vectors in the
bundle rather than CDN assets, for the reasons in `components/art/frame.tsx`,
and they follow the rules that can be checked mechanically — one object, heavy
outline, no text inside, legible without colour. What cannot be checked
mechanically is whether an Egyptian four-year-old looks at the drawing for
`hh_bag` and says **شنطة**. Several are culturally specific in exactly the way
that goes wrong quietly: `hh_table` (ترابيزة), `hh_shoes` (جزمة),
`hh_water_glass` (كوباية مية) as distinct from `hh_cup` (كوباية). A
misrecognised picture does not fail — it records the child as not knowing a word
they know perfectly well, and BKT then schedules more of it.

**2. Twenty-five letter keywords I invented.** `docs/02 §10.1` gives three
(أ → أسد, ب → بطة, ت → تفاحة) and those are transcribed. The other 25 — ث → ثعلب,
ج → جمل, ح → حصان and so on — are an agent's choices, made for concreteness. A
keyword carries the letter's *sound*, so choosing one is a phonics decision and
belongs to a speech therapist. `REVIEWED_LETTER_KEYWORDS` names the three that
are real; a test asserts `REVIEWED_BY` in that file is still empty.

**3. Eighty-eight `alt_ar` strings**, agent-written. They are the only channel a
caregiver's screen reader has for these pictures, and `docs/06 §5` makes alt
text a mandatory column rather than a nicety.

**One decision that is not a review, and is yours.** `docs/04c §C05`'s session
manifest carries enough to render `listen_point` and nothing else, while
`docs/01 §1`'s `activity_kind` enum has five values. I added four optional
fields — `card`, `bins`, `beats` and `spoken_ar` — marked `ADDITION` in
`lib/manifest.ts` where they are declared. They should either move into the C05
contract or the other four kinds should be cut from the enum; carrying an enum
value the manifest cannot express is the state that produces a blank screen.

---

## Not open, for the record

Mechanical and mine to close — all currently green:

- The random-tapper test (0/1000 at every choice count).
- All four CI guard checks, each with a violation fixture *and* a control
  fixture proving it fires correctly.
- 100% branch coverage on every `domain/` package, the guardrails and the gateway.
- The banned-terms lint and the no-physical-CSS rule.
