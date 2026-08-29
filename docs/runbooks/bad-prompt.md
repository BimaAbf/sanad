# A bad prompt shipped

## The fast path: no deploy required

Prompts resolve from Langfuse by label, with the text baked into the image only
as an outage fallback. So:

1. Langfuse → the prompt → move the production label back to the previous
   version.
2. Confirm at `/console/ai-calls`: new calls should show the older
   `prompt_version` within one cache TTL.
3. Run the eval suite for that decision point and attach the numbers to the
   incident.

Minutes, and it does not touch the container.

## If output already reached caregivers

Two situations, and the second is much more serious than the first.

**Narrative or summary text** — friendly copy, no clinical claim. Note it, fix
the prompt, move on.

**Anything that influenced a recorded verdict** — a `pgee_interpret` result
written to `assessment_responses`, or a mastery judgement. Stop and follow the
scoring-correctness runbook in docs/07 §6: freeze, re-score from the stored raw
responses, regenerate, notify. The raw responses are retained precisely so that
a bad interpretation is recoverable without asking a parent to sit through fifty
questions about their child a second time.

## Do not

- Do not edit the prompt forward under pressure. Revert first, diagnose second.
  A second bad version shipped during an incident is how a small problem becomes
  a long one.
- Do not skip the eval run because the revert obviously fixes it. The eval is
  what turns "it looks better" into a number in the incident record.
