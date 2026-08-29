# 03 — The other credentials

Everything in [`SETUP.md` §2](../../SETUP.md) that is not Groq. None of it blocks
development: each has a deterministic or fixture fallback, and `just up` prints
which are absent and what each absence costs.

**Where they go.** All of them live in `.env` at the repo root, which is
gitignored. `.env.example` is committed and must never gain a value — it is the
template, and a key pasted into it is a key in the git history.

---

## `ANTHROPIC_API_KEY` — Gate 4

DP1 (interpret) and DP4 (report), per
[docs/12 §2](../12-stack-revision-groq-selfhosted-voice.md).

```
ANTHROPIC_API_KEY=sk-ant-...
```

From <https://console.anthropic.com>. Set a **spend limit on the key** before
you use it; `docs/12` budgets $0.14–0.37 per child per month and a runaway loop
is the way that number stops being true.

**Without it:** the gateway replays recorded fixtures and makes no network call.
The eval sets, the guardrail tests and every decision point are exercised
without it — that is the design, not a workaround.

**What it additionally unlocks:** the empirical half of the prompt-cache guard.
`tools/guards/prompt_cache_hit.py` checks prompt *layout* statically today; with
a key it can also assert that `cache_read_input_tokens` is non-zero on the
second identical call, which is the only way to know caching actually hit.

---

## Cloudflare R2 — Gate 5

Audio and media hosting. Needed to *serve* the rendered corpus; not needed to
build or test anything.

```
SANAD_R2_ACCOUNT_ID=
SANAD_R2_ACCESS_KEY_ID=
SANAD_R2_SECRET_ACCESS_KEY=
SANAD_S3_BUCKET=sanad-media
SANAD_S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
```

R2 is S3-compatible, so the same `SANAD_S3_*` variables the local MinIO uses
point at it — swap the endpoint and the credentials and nothing in the code
changes. Create two buckets to match the local stack: `sanad-media` (public via
CDN) and `sanad-private` (never public).

Egress is free, which is why [docs/12 §3.3](../12-stack-revision-groq-selfhosted-voice.md)
picks it over CloudFront for a static tier served to Egypt.

**Without it:** MinIO in `docker-compose.yml` covers local development
completely — console at <http://localhost:59001>, `sanadminio` /
`sanadminio-dev-secret`.

---

## GPU provider — Gate 5

Thunder Compute or equivalent, for the VoxCPM2 render and later the Qwen3-ASR
host. **~$0.35/hr and about two hours, once.**

Do not buy this before you have a recording. The pipeline has nothing to render
until [01](01-nour-voice.md) is done, and the real blocker there is the voice
talent, not the GPU.

**Do not run a single always-on GPU as the production ASR tier.** One GPU on one
provider is a single point of failure in a live child-facing path. For the pilot
use Groq Whisper — [docs/12 §3.3](../12-stack-revision-groq-selfhosted-voice.md)
sizes the free tier at 28,800 audio-seconds a day, roughly 120× what eight
families need — and keep the scale-to-zero GPU for later, with Groq as automatic
failover and caregiver confirmation behind that.

---

## SMS aggregator — Stage 1, real-device testing only

OTP delivery.

```
SANAD_SMS_PROVIDER=twilio          # or local_aggregator
```

plus whichever credentials that provider needs.

**Without it:** `SANAD_SMS_PROVIDER=null` prints the code to the console and the
entire auth flow works end to end. You only need a real aggregator when you want
the code to arrive on an actual phone.

For Egypt specifically, a local aggregator generally delivers more reliably than
an international one, and sender-ID registration has its own lead time — worth
starting before you need it, not when.

---

## `AZURE_SPEECH_KEY` — contingency only

Only needed if VoxCPM2 loses the listening test in
[01 §6](01-nour-voice.md). Do not buy it speculatively.

---

## Not needed at all

Langfuse (self-hosted in `docker-compose.yml`), Postgres, Redis, MinIO and
Mailhog (all local), and OpenAI (dropped in the doc-12 revision).

---

## Checking what the app sees

```bash
just up --no-web
```

The preflight prints every credential as `[set ]` or `[none]`, and for each
absent one, the mode the system runs in instead. It reads `.env` and the
environment and **never prints a value** — a variable set to an empty string
counts as absent, because an empty key is a misconfiguration, not a credential.
