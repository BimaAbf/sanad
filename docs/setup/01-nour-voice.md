# 01 — The Nour voice

**Closes REVIEW-QUEUE [#10](../../REVIEW-QUEUE.md) and [#11](../../REVIEW-QUEUE.md).
Longest lead time in the project. Nothing has started.**

Nour is the only voice this product will ever have.
[Assumption C7](../00-assumptions.md) makes voice consistency a comprehension
aid for children with Down syndrome, which means the voice you cast is frozen
for the product's life. That is why this is a casting decision and a contract
before it is an engineering task.

> **What happens while this stays open:** the child app plays static audio files
> from a CDN. The CDN is empty. No session can run at all. Everything else in
> the product works and is tested; there is simply no sound.

---

## 1. Cast

**Who.** An Egyptian woman who is used to speaking with small children —
[docs/12 §3.1](../12-stack-revision-groq-selfhosted-voice.md) suggests an
early-intervention specialist or a mother, and that is the right instinct. You
are not casting a voice actor. You are casting someone whose default register
when addressing a three-year-old is already correct, because that register is
what the clone reproduces and it is very hard to fake for 25 minutes.

**What to listen for, in a two-minute audition clip:**

| | Why |
|---|---|
| Egyptian colloquial, not MSA and not Gulf | جزمة must be /gazma/. A child taught /dʒazma/ learns a word their family will not recognise, and the whole product rests on the child mapping a sound to an object in their own house. |
| Naturally slow, without sounding slowed-down | The corpus is rendered at `rate="-15%"` for auditory-short-term-memory limits ([04d §2](../04d-components-voice.md)). A voice that is already unhurried survives that; a fast voice slowed down sounds drugged. |
| Warm without performing | She will be heard dozens of times per session. Anything theatrical becomes grating by the tenth repetition, and this is the most common way a children's voice goes wrong. |
| Clean final consonants | The child is learning to reproduce these words. A voice that trails off teaches a trailed-off word. |
| No smoker's rasp, no vocal fry, no strong sibilance | All three survive cloning and all three are fatiguing. |

**Ask three candidates for the same two-minute clip and pick blind.** Have the
native-speaker reviewer (REVIEW-QUEUE #6) listen too — they are hearing dialect,
you are hearing warmth, and both matter.

**Budget.** Half a day of her time, plus a studio. This is not a large expense
and it is the one you should not economise on.

---

## 2. Wait for the words

**Do not book the studio until [REVIEW-QUEUE #6](../../REVIEW-QUEUE.md) is
closed.** The 88 curriculum labels in `seeds/curriculum.py` are transcribed from
the architecture package, but their **vowelisation is mechanically generated and
has never been reviewed**, and `REVIEWED_BY` is empty. Recording 25 minutes of
subtly wrong Arabic and cloning it is the expensive way to discover that.

The check is one line:

```bash
grep 'REVIEWED_BY' services/api/seeds/curriculum.py
```

Empty string means not yet. CI fails while it is empty, on purpose.

---

## 3. Generate the script

```bash
just voice-script
```

Writes `dist/nour-recording-script.md` — the document you hand the studio. It is
assembled from the repo's own curriculum rather than a generic phonetic wordlist,
because a clone reproduces the register it was trained on: twenty minutes of
neutral reading produces a Nour who reads.

It contains:

1. **Warm-up** — three lines and 30 seconds of room tone, discarded.
2. **The words** — all 88 labels, two takes each.
3. **The instructions** — the six sentence frames the product speaks.
4. **Praise** — recorded last, three takes each, on purpose: praise recorded in
   the first ten minutes of a session sounds like someone reading, and it is the
   utterance a child hears most.
5. **Encouragement** — the retry and unclear lines. The direction on this block
   is the most important one in the session: none of these lines corrects the
   child and none may sound disappointed.

Then a **phonetic-coverage report**, which is a real check and can fail: it lists
any phoneme the product's grapheme-to-phoneme table can produce that never
occurs in the script. A clone that has never heard the talent produce /ʕ/
extrapolates it. Today the 88 labels cover all 26.

**The script is about five minutes short of the 20-minute floor, and the tool
says so rather than padding.** The curriculum is isolated words; a clone trained
only on isolated words gives every synthesised sentence list-prosody. Fill the
gap with **connected Egyptian speech in the same register** — ask the
native-speaker reviewer to write or improvise ten minutes of it, or have the
talent read a children's picture book. That passage is deliberately not
generated: it is exactly the content REVIEW-QUEUE #1 and #6 exist to keep an
agent from inventing.

---

## 4. Sign the release — before the microphone, not after

**This is a contract, not a formality.** You are cloning a real person's voice
and shipping it to thousands of children, and C7 then says that voice can never
change — so you cannot re-cast if the relationship sours. Get a lawyer to draft
it. At minimum it must grant:

- [ ] **Perpetual** licence to synthetically reproduce her voice. Not a term of
      years — C7 means the product cannot outlive the licence.
- [ ] **Transferable** and sub-licensable, so the licence survives a sale,
      restructuring, or a change of operating entity.
- [ ] Rights to **derive and retain a model artefact** (the LoRA adapter), not
      just to use the recordings.
- [ ] Scope covering **this product and its successors**, in every territory.
- [ ] **Moral-rights waiver** where the jurisdiction recognises one, or an
      equivalent consent to modification — the render alters rate, pitch and
      emphasis per utterance.
- [ ] Explicit statement that she is **not** entitled to be re-engaged for
      changes, and correspondingly that the voice will not be used for anything
      outside the product's scope. Name what is out of scope: advertising,
      political content, any other product.
- [ ] A **credit and a fee**, both stated. Anonymity is not a substitute for
      payment, and she should be credited if she wants to be.

Egypt PDPL 151/2020 treats voice as personal data. Her consent to the processing
is separate from her licence of the recording, and both need to be in the
document. This is a question for the same lawyer who reads the Groq DPA
([02](02-groq-and-model-licences.md)).

---

## 5. Record

The full engineering spec is in the generated script's *Before the session*
table. The four that matter most:

| | |
|---|---|
| **48 kHz, 24-bit, mono WAV** | No compression, no noise reduction, no EQ. The clone is trained on the raw signal; processing it first bakes an artefact into every utterance the product will ever say. |
| **One session, one setup** | One mic, one position, one set of levels. If a second session is unavoidable, photograph the setup first. Inconsistency across a cloning corpus shows up as a voice that shifts character mid-sentence. |
| **Keep every take** | Do not comp in the studio. Take selection is a judgement to make later with the speech therapist. |
| **Peaks around −12 dBFS** | Headroom beats loudness; the corpus is normalised to −16 LUFS afterwards anyway. |

Deliverable: a folder of WAVs, one per take, named so a take maps to a script
line. Plus the 30 seconds of room tone.

---

## 6. Clone, then hold the listening test

Clone with VoxCPM2 per [docs/12 §3.1](../12-stack-revision-groq-selfhosted-voice.md).
Then, **before rendering 850 files**, run the gate that decides the whole TTS
choice — REVIEW-QUEUE #11:

1. Render **20 of the actual skill labels**, not a demo sentence.
2. Include the ones that expose dialect: `جزمة` must come out /gazma/ and not
   /dʒazma/; `جبنة` must be /gebna/.
3. Have a native Egyptian speaker rate them **blind against the Azure
   `ar-EG-SalmaNeural` equivalents** on intelligibility and dialect
   authenticity.
4. **If VoxCPM2 loses, keep Azure for TTS and take the rest of the doc-12
   revision.** That is the documented decision rule, and it is written down
   precisely so the sunk cost of getting this far does not decide it.

Half a day. Record the outcome in an ADR either way.

---

## 7. Render and publish

**`renderer.py` does not exist yet.** What exists and is tested:

| Written | Not written |
|---|---|
| `voice_render/plan.py` — the render plan, content-hash idempotency, the GPU-hour and cost estimate, orphan detection, the unvowelised hard-stop | `voice_render/renderer.py` — the VoxCPM2 call itself |
| `voice/domain/inventory.py` — the ~850-utterance enumeration, and `missing_assets()`, which is the publish gate | the R2 upload and `tts_cache` write |
| `voice/domain/ssml.py` — SSML construction, the −16 LUFS target and tolerance | |

So step 7 is: write `renderer.py` against the interface `plan.py` already
assumes, rent an A6000 (~$0.35/hr, about two hours), render, loudness-normalise
to −16 LUFS, encode to Opus, upload to R2, write the cache rows, **shut the GPU
down**. About **$0.70** of GPU time. Runtime cost from then on is zero — there
is no runtime TTS anywhere in a child's path.

`missing_assets()` returning a non-empty list is a publish blocker, not a
warning: an utterance missing from the corpus reaches a child as silence.

Re-renders are cheap by construction — the plan diffs on content hash, so
fixing the tashkeel on four words is a four-clip render, not 850.

---

## What to do this week

- [ ] Shortlist three candidates and ask each for the same two-minute clip.
- [ ] Send the release draft to a lawyer. It has the longest tail of anything here.
- [ ] Chase REVIEW-QUEUE #6 — the native speaker gates both the script and the render.
- [ ] Run `just voice-script` and read the output, so you know what you are
      commissioning before you commission it.

Nothing on that list needs a credential, a GPU or a deployed environment.
