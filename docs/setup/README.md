# Setup — the things only you can do

[`SETUP.md`](../../SETUP.md) is the register: what is outstanding, and its status.
[`REVIEW-QUEUE.md`](../../REVIEW-QUEUE.md) is the queue: what needs a human decision.
**This directory is the procedures** — how to actually do them.

**If what you want is the API keys** — which ones exist, which are free, and
what each actually turns on — start at
[00 — API keys quickstart](00-api-keys-quickstart.md).

**If what you want is to see it running,** start at
[04 — running it in its deployed shape](04-running-it-deployed.md). It goes from
a machine where nothing has run to production settings, real datastores and both
apps served — and is explicit about what cannot work end to end yet.

Nothing here is needed to run the project. `just up` starts everything on
fixtures and deterministic fallbacks with zero credentials, and it prints which
ones are absent and exactly what each absence costs. These guides are for the
point where you want real audio, real model calls, or a pilot.

| Guide | Closes | Lead time |
|---|---|---|
| [01 — the Nour voice](01-nour-voice.md) | REVIEW-QUEUE #10, #11 | **weeks** — start first |
| [02 — Groq, and two model licences](02-groq-and-model-licences.md) | REVIEW-QUEUE #13 | days, mostly legal |
| [03 — the other credentials](03-other-credentials.md) | SETUP §2 gates 4 and 5 | an hour each |
| [04 — running it in its deployed shape](04-running-it-deployed.md) | BLOCKED #1, and the honest ceiling | an afternoon |

---

## The order, and why it is this order

```
week 1   ├─ 01 §1  cast the voice ─────────────────┐   longest lead time in the
         │                                          │   project; nothing else
         ├─ 02 §1  open a Groq account, ask for     │   here is on the critical
         │         the DPA ──────────────────┐      │   path for audio
         │                                    │      │
         └─ 03     paste the two API keys ─┐  │      │
                                            │  │      │
week 2-3   REVIEW-QUEUE #6: a native ───────┼──┼──────┤  ← the real gate
           speaker vowelises the 88 labels  │  │      │
                                            │  │      │
           01 §3  sign the release ─────────┼──┼──────┤
                                            │  │      │
week 3-4   01 §5  record ───────────────────┼──┼──────┘
                                            │  │
           01 §6  clone, listening test ────┤  │
           01 §7  render, publish ──────────┘  │
                                               │
before any pilot traffic ──────────────────────┘
           02 §2  DPA signed, retention stated, no training on our data
```

Two dependencies in there are easy to miss and both stop the audio dead:

* **The 88 labels are unvowelised placeholders.** `seeds/curriculum.py` ships
  `label_vowelised` as a mechanically-generated placeholder and `REVIEWED_BY` is
  empty. Unvowelised Arabic sent to a TTS engine mispronounces reliably — it is
  the single most common Arabic TTS bug — so the render pipeline *refuses* to
  publish an unvowelised item rather than teaching a child a wrong word. Booking
  a studio before REVIEW-QUEUE #6 is closed means recording the wrong words.
* **There is no renderer yet.** `tools/voice_render/plan.py` computes what to
  render, what to skip and what blocks a publish, and it is tested. The module
  that actually calls VoxCPM2 — `renderer.py` — has not been written, because
  writing a model call that has never had a model, a GPU or a voice to call it
  with produces code that reads correctly and does not run. It is a day's work
  once §5 and §6 are done, and it is the last step, not the first.

## What is genuinely blocking versus merely absent

| | Blocks development? | Blocks a pilot? |
|---|---|---|
| Groq DPA (02) | no | **yes — hard stop** |
| Nour recording (01) | no | **yes — no audio, no session** |
| Vowelised labels (REVIEW-QUEUE #6) | no | **yes — same** |
| `ANTHROPIC_API_KEY` (03) | no | no — fixtures cover the eval set |
| Cloudflare R2 (03) | no | no — MinIO covers local; needed to serve audio |
| SMS credentials (03) | no | no — the OTP prints to the console |
