# Voice / ASR outage

**Expected impact on a child: none.** docs/04d §7 and docs/12 §3.3 give three
layers, and the last of them needs no vendor at all:

```
Qwen3-ASR (self-hosted)  →  Groq Whisper  →  caregiver confirmation
```

## Confirm

1. `GET /voice/health` — which recognisers are configured, in failover order.
2. `/console/ai-calls` is NOT where voice failures appear. Nothing about voice
   touches the LLM gateway (docs/04d §5), so look in the API logs for
   `asr_provider_failed`.

## Do

Nothing, in the normal case. `AsrChain` falls through automatically and the
session switches to caregiver-confirmation mode, with a small badge explaining
why — to the caregiver, never to the child.

Confirm the degradation is behaving:

- An expressive activity still completes: the model audio plays and the
  "قالها صح ✅" button records a `caregiver_confirmed` attempt at half weight.
- With no caregiver interaction either, the activity becomes say-it-together,
  which is still a real teaching act.
- **Attempt 2 is accepted regardless of what was heard.** If a child is being
  told they were wrong during an ASR outage, that is a defect, not a
  degradation. Escalate it.

## If the GPU tier is the problem

Scale it to zero and let Groq Whisper carry the load. docs/12 §3.3 sizes the
free tier at 28,800 audio-seconds a day, which covers the pilot roughly 120
times over. There is no urgency about bringing the GPU back.

## Do not

- Do not disable expressive activities wholesale. Caregiver-confirmation mode is
  a working mode, not a broken one — and it is the mode that produces the
  labelled data the ASR fine-tune needs (docs/12 §3.2).
- Do not raise the acceptance threshold to compensate for a worse recogniser.
  The 0.55 threshold is a clinical judgement about false accepts versus false
  rejects. It is not a tuning knob for provider quality.
