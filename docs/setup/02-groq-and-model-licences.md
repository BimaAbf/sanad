# 02 — Groq, and two model licences

**Closes REVIEW-QUEUE [#13](../../REVIEW-QUEUE.md).
Blocks any pilot traffic, including pseudonymised. Does not block development.**

Two separate things live in this file and they have different urgencies:

* **§1 — the key.** Ten minutes. Unblocks live-AI smoke tests and the eval runs.
  Safe to do today; a key on a machine with no pilot data on it is low risk.
* **§2 — the data terms.** Days, and it needs a lawyer. This is the one that is
  actually blocking, and §1 does not close it.

Doing §1 and calling #13 closed is the failure mode this file exists to prevent.

---

## 1. Get a key and put it in `.env`

1. Sign up at <https://console.groq.com>.
2. Create an API key. Name it for this project so it can be revoked in isolation.
3. Add it to `.env` — **not** `.env.example`, which is committed:

   ```
   GROQ_API_KEY=gsk_...
   ```

4. Confirm the app sees it:

   ```bash
   just up --no-web
   ```

   The preflight prints a credentials table. `GROQ_API_KEY` should move from
   `[none]` to `[set ]`. It never prints the value.

**What the key does and does not turn on.** `AI_LIVE=0` is the default
everywhere, and with it the gateway makes **no network call at all** — it
replays recorded fixtures. That is not a test convenience; it is how the whole
product is built and verified. A key present with `AI_LIVE=0` changes nothing.
Live calls need the flag as well, which is deliberate: it means you cannot spend
money, or send data anywhere, by accident.

**What it costs to be wrong here.** Nothing, if §2 is respected. The key alone
does not put a child's data anywhere.

---

## 2. The data terms — the part that is actually blocking

[docs/12 §2](../12-stack-revision-groq-selfhosted-voice.md) is unambiguous, and
it is the reason #13 exists:

> Groq's free-tier data terms are not established… Before any pilot traffic —
> even pseudonymised — someone must read those and confirm: no training on our
> data, a stated retention period, and a signed DPA. This is child
> health-adjacent data in a PDPL jurisdiction.

**Do not treat "free tier" and "paid tier" as the same question.** Free tiers
commonly reserve training rights that paid tiers do not. If the answer to any of
the three below is only available on a paid plan, the answer for this product is
to be on the paid plan.

### The three answers to get in writing

| Ask | What "acceptable" looks like | Where to look first |
|---|---|---|
| **Is our input used to train or improve models?** | An unqualified no, covering the tier we are actually on. "We do not train on API data by default" is not the same answer — find out what turns the default off, and whether it is on for the free tier. | Terms of Service; the privacy or data-usage page; the DPA |
| **How long is our data retained, and where?** | A stated maximum in days, a stated purpose (abuse monitoring is normal), and a named region or sub-processor list. "Retained as long as necessary" is not a retention period. | DPA; sub-processor list; any regional-processing addendum |
| **Will they sign a DPA?** | A countersigned Data Processing Agreement naming us as controller and them as processor, with sub-processors listed and a breach-notification window. | Their legal or enterprise contact — ask directly; self-serve tiers often have one available on request |

Ask by email so the answer is a document. Screenshots of a marketing page are
not a contract, and terms change.

### The PDPL framing, because it changes what "acceptable" means

Egypt's Personal Data Protection Law 151/2020 governs this, and two facts make
the bar higher than an ordinary SaaS review:

* **The data subjects are children.** Consent is given by a caregiver and the
  processing is on their behalf.
* **The data is health-adjacent.** Developmental assessment output, session
  performance, and — if `voice_retention` consent is given — a child's recorded
  voice. Voice is biometric-adjacent in most modern regimes.

Pseudonymisation reduces the risk; it does not remove the obligation, which is
exactly why REVIEW-QUEUE #13 says "including pseudonymised."

Note what the architecture already does for you here, because it narrows the
question rather than answering it: `app/ai/redaction.py` pseudonymises before
anything crosses the gateway, and **no audio, no transcript and no embedding is
ever sent to the LLM** ([04d §5](../04d-components-voice.md)) — the voice module
does not import the gateway, and a CI guard fails the build if any module other
than the gateway constructs a provider client. So what actually reaches Groq is
a narrower set than "the child's record". Take the list of what does reach it to
the lawyer rather than the whole data model.

### Record the outcome

Write `docs/adr/018-groq-data-terms.md` with the answers, the date, and the
version of the terms you read. Terms change and the ADR is what tells a future
reader whether the review is still valid.

**Until that ADR exists, no pilot traffic.** Development is unaffected — the
fixtures were built for exactly this.

---

## 3. Two model licences, both load-bearing

[docs/12 §3.4](../12-stack-revision-groq-selfhosted-voice.md) flags these and
they have not been checked. Neither blocks development; both block shipping the
thing they underpin.

### VoxCPM2

- Commercial-use terms for the weights.
- **Whether a voice cloned from a consented recording carries any restriction.**
  This is the non-obvious one, and it interacts directly with the release in
  [01 §4](01-nour-voice.md): you can hold a perfect licence from the talent and
  still be restricted by the model's terms.
- Whether the derived LoRA adapter may be retained and redistributed.

If the answer is bad, the fallback is Azure `ar-EG-SalmaNeural` — which is also
the fallback if VoxCPM2 loses the listening test, so it is a contingency the
project already has.

### Qwen3-ASR-1.7B

- Commercial use.
- **Distribution of a fine-tuned derivative.** This one is strategic, not
  operational: [docs/12 §3.2](../12-stack-revision-groq-selfhosted-voice.md)
  argues that the caregiver-override button is a data-collection mechanism for a
  Down-syndrome Egyptian child-speech fine-tune that nobody else has. If the
  licence forbids distributing a derivative, that argument collapses and the ASR
  choice should be re-decided on accuracy alone.

Record both in `docs/adr/019-model-licences.md`.

---

## What to do this week

- [ ] Create the Groq key and paste it into `.env` (ten minutes, no risk).
- [ ] Email Groq asking the three questions in §2 and requesting a DPA.
- [ ] Send the same lawyer the VoxCPM2 and Qwen licence questions **and** the
      Nour voice release from [01 §4](01-nour-voice.md) — one engagement, three
      documents.
- [ ] Do not send pilot traffic until the DPA is countersigned.
