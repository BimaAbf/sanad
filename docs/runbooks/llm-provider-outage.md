# LLM provider outage

**Expected impact on a family: none.** Every AI decision point has a
deterministic fallback, and the product is designed so a caregiver cannot tell
the difference except that a narrative reads like a template. That is the claim;
this runbook is how you confirm it is holding.

## Confirm

1. `/console/ai-calls` → filter `outcome = provider_error`. A spike on ONE
   decision point is a routing problem; a spike on all of them is the provider.
2. The AI-health dashboard: refusal rate, schema error rate, p95 latency.
3. Check which provider. docs/12 §2 routes `pgee_interpret` and `pgee_report` to
   Anthropic and everything else to Groq — so an Anthropic outage affects
   assessments only, and a Groq outage affects play sessions only.

## Do

**Usually nothing.** The circuit breaker trips after 10 consecutive failures and
the deterministic path takes over on its own.

Verify rather than intervene:

- A play session still completes end to end. The plan comes from `resolve_plan`
  deterministic ordering; the summary ships from the template.
- An assessment still advances. `pgee_next_item` falls back to the engine own
  choice, which is the ground truth the AI was only ever re-ranking.
- The degraded banner appears in the caregiver app.

Intervene only if the breaker has NOT tripped and errors are still reaching
users: trip that decision point flag at `/console/flags`. It takes effect within
30 seconds, without a deploy.

## Do not

- Do not switch a decision point to a different provider to "keep quality up".
  `pgee_interpret` sits on Anthropic because docs/12 §2 measured that choice.
  Moving it to a model that has not cleared `interpret_ar.jsonl` at ≥95% exact
  match with 100% red-flag recall means one in eight developmental judgements
  may be wrong — written into a clinical record, silently.
- Do not raise the retry count. The SDK already retries three times; more
  retries during an outage lengthen every request and turn a degraded product
  into a slow one.

## After

An assessment completed during the outage carries `plan_source =
deterministic_fallback` on its rows. That is not a defect and does not need
re-running. Note it in the incident so that a later quality review does not read
the absence of AI interpretation as a bug.
