# 00 — API keys: what to get, in what order, and what each one actually turns on

**Start here before [01](01-nour-voice.md), [02](02-groq-and-model-licences.md) or
[03](03-other-credentials.md).** Those three are the deep procedures. This is the
short version: every credential the project can use, whether it is free, and —
the part that is easy to get wrong — what the code does differently once you set
it.

> **The first thing to know: you need none of these to run SANAD.**
> `just up` brings up the whole stack today with zero credentials. Onboarding,
> OTP sign-in, creating a child, the consent ledger, the 88-skill map and the
> progress dashboard all work with nothing set. The keys below turn on the *AI*
> and the *deployment* surfaces, not the product.

---

## The one-minute version

| Key | Free? | Turns on | Get it before |
|---|---|---|---|
| *(nothing)* | — | The whole app: sign-in, child, consent, skills, progress | now |
| `GROQ_API_KEY` | **Yes**, free tier | **Both** the AI decision points (it is the default provider) and speech recognition | you want either to work |
| `AI_LIVE=1` | — | Nothing on its own. **Required alongside a provider key** to make any live call | you want live AI instead of fixtures |
| `ANTHROPIC_API_KEY` | **No** — usage-billed | The same decision points, via `AI_PROVIDER=anthropic` | only if you choose Anthropic over Groq |
| Cloudflare R2 (3 vars) | **Yes**, 10 GB free | Media hosting when deployed. MinIO covers local entirely | you deploy |
| SMS aggregator | No | Real OTP texts. `NullSms` prints the code to the log | real-device testing |
| GPU provider token | No | Voice rendering — **do not buy yet**, see below | there is a recording |
| `AZURE_SPEECH_KEY` | Yes, free tier | Contingency TTS only | never, unless VoxCPM2 fails |

**If you want to spend nothing: get the Groq key and set `AI_LIVE=1`. That is
the whole AI layer, free.** Groq is the default provider, so you do not need a
paid Anthropic key to see live AI at all.

---

## 1. Groq — free, ten minutes, do this one

Groq has a genuinely free tier and it is the only credential here that both
costs nothing and visibly changes the product.

1. Sign up at <https://console.groq.com>.
2. Create an API key. Name it for this project so it can be revoked alone.
3. Put it in `.env` — **not** `.env.example`, which is committed:

   ```
   GROQ_API_KEY=gsk_...
   ```

4. Restart and check the log line. `just up` prints `services_wired count=N`.
   With no key that is `count=0` and the line above it reads
   `asr_no_providers_configured`. With the key it becomes `count=1`.

**What it turns on — two separate things.**

1. **Speech recognition.** It builds a Whisper (`whisper-large-v3-turbo`)
   provider into the ASR chain, so `POST /voice/attempt` transcribes a child's
   utterance instead of answering "unavailable".
2. **The AI decision points.** `AI_PROVIDER` defaults to `groq`, so with
   `AI_LIVE=1` the gateway routes interpret/report/tutor to Groq
   (`openai/gpt-oss-120b`). This is the part that means you do not need to pay
   anyone to see the AI layer work.

The two are independent: the ASR provider is built from the key alone, while
the decision points additionally need `AI_LIVE=1`.

**Free-tier limits are real but generous here:** a child's attempt is a
one-to-three-second clip, and docs/12 §1 puts the free audio-seconds allowance at
roughly 120× what the pilot needs.

> **Before any pilot traffic** — even pseudonymised — the data terms in
> [02 §2](02-groq-and-model-licences.md) still have to be answered in writing.
> A key on your own machine with test data on it is low risk. A key with a real
> family's child on it is a PDPL question. That has not changed.

---

## 2. Anthropic — optional, and the only one that costs money

There is no free tier; it is usage-billed at <https://console.anthropic.com>.
You only need it if you deliberately choose Anthropic over the Groq default:

```
ANTHROPIC_API_KEY=sk-ant-...
AI_PROVIDER=anthropic
AI_LIVE=1
```

docs/12 §2 routes every decision point to Groq and leaves DP1 (interpret) open
pending the `interpret_ar` eval — so Anthropic is the answer to "is Opus better
at interpreting an Egyptian caregiver's free text", not a prerequisite.

**A key plus `AI_LIVE`, or nothing happens.** This is deliberate and worth understanding
because it is the safety property the whole architecture is built on:

* With `AI_LIVE` unset, the gateway makes **no network call at all**. It replays
  recorded fixtures. A key sitting in `.env` with `AI_LIVE` off changes nothing
  and costs nothing.
* With `AI_LIVE=1` and no key for the selected provider, the API **refuses to
  start** and names the variable. It does not quietly fall back to fixtures — a live-AI test that
  passed without reaching a model would be worse than a failing one.

**Expected cost.** docs/12's revised routing lands at **$0.14–0.37 per child per
month**, against the $6/child/month ceiling in SETUP.md O4. Development traffic
is a few calls at a time; you are not going to be surprised by a bill.

**One thing to expect on the first live run:** there are currently **no fixtures
in the repo** (`services/api/tests/fixtures/ai/` does not exist). Every call with
`AI_LIVE` off therefore returns `NO_FIXTURE` rather than a recorded answer. The
gateway now *writes* a fixture after each successful live call, so the corpus
builds itself the first time you run with a key — which is how it was always
meant to be produced.

---

## 3. Cloudflare R2 — free, and only when you deploy

10 GB storage and no egress fees on the free tier. **Do not bother locally**:
`docker-compose` runs MinIO, and the readiness probe already reports `s3: ok`
against it.

R2 is S3-compatible, so the whole migration is configuration:

```
SANAD_S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
SANAD_S3_ACCESS_KEY_ID=...
SANAD_S3_SECRET_ACCESS_KEY=...
SANAD_S3_BUCKET=sanad-media
```

No code changes — `S3AudioSink` and the readiness probe both go through the same
`aioboto3` session and neither knows which one it is talking to. Details in
[03](03-other-credentials.md).

---

## 4. SMS — you almost certainly do not need it

`SANAD_SMS_PROVIDER=null` is the default, and `NullSms` prints the OTP straight
into the log:

```
[NullSms] -> +201012345678: كود الدخول لسند: 012314
```

The full auth flow — request, verify, RS256 token, refresh rotation — works
end to end with that. You only need a real aggregator when you want the code to
arrive on an actual handset during device testing.

---

## 5. What NOT to buy yet

**The GPU provider token (Thunder Compute or equivalent).** It renders the Nour
voice. There is nothing to render: the voice talent has not been recorded, which
is REVIEW-QUEUE #10 and the longest-lead item in the project. Buying GPU time
before there is a recording buys idle time. Get the recording first —
[01](01-nour-voice.md) has the casting brief and `just voice-script` writes the
script.

**`AZURE_SPEECH_KEY`.** Contingency only, for if VoxCPM2 loses the listening
test (REVIEW-QUEUE #11). That test has not been run.

---

## 6. So what does "test it for deployment" actually need?

Honestly: the keys are not the blocker. Two things are.

**What works right now, keys or not.** Sign-in by OTP, creating a child, the
consent ledger, the 88-skill map, the progress dashboard, the readiness probe,
and both databases under migration. `just up` and `just up-prod` both run the
real thing.

**What no key will fix, because the code is not there.**

* **The assessment engine has no persistence.** `assessment/` is domain logic
  only — no models, no repository, no table. So there are no assessments, and
  the journey view correctly answers `insufficient_data` forever. This is the
  single biggest gap between "runs" and "usable".
* **The play session has no endpoints.** The child app's `/play` screen posts
  attempts into an outbox whose sender is a hardcoded `async () => ({ok: true})`.
  `POST /play/sessions` does not exist.
* **Nothing has ever been deployed.** PROGRESS.md P15 says it plainly: the
  Terraform has never been applied and CI has never run. `just up-prod` runs the
  deployed *shape* on your machine; it is not a deployment rehearsal.

**The order I would go in:** get the free Groq key today and set `AI_LIVE=1` —
ten minutes, no cost, and it lights up both the microphone and the AI layer.
Leave Anthropic alone until the `interpret_ar` eval says Opus is worth paying
for. Then spend the effort on assessment persistence, because that is what the
product is actually missing, and no credential substitutes for it.
