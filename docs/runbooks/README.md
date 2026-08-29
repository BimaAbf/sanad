# Runbooks

One file per situation from [docs/08 §7](../08-infrastructure.md). Each is
written to be followed at 03:00 by someone who did not build the thing.

⚠️ **None of these has been rehearsed.** There is no deployed environment. The
steps are derived from the design, not from having done them. The two that
matter most — the restore drill and the kill-switch exercise — are acceptance
criteria in docs/09 P15 and are recorded as outstanding in PROGRESS.md.

| Runbook | When |
|---|---|
| [llm-provider-outage.md](llm-provider-outage.md) | Anthropic or Groq is down or slow |
| [voice-outage.md](voice-outage.md) | ASR is unreachable |
| [cost-spike.md](cost-spike.md) | A child or a decision point is burning budget |
| [bad-prompt.md](bad-prompt.md) | A prompt version is producing bad output |
| [db-restore.md](db-restore.md) | Data loss, corruption, or the quarterly drill |
| [escalation-sla-breach.md](escalation-sla-breach.md) | A safety escalation is about to miss its SLA |

The scoring-correctness runbook — what to do when a bug is found in code that
produced a developmental age already shown to a parent — lives in
[docs/07 §6](../07-security-privacy.md), because it is a clinical and legal
procedure before it is an operational one.

## The rule under all of them

> Degrade, do not fail. Every AI and voice dependency in this product has a
> deterministic fallback, and the fallback is the normal path with a vendor
> removed. If you are choosing between "return an error to a caregiver" and
> "run the deterministic path and log it", it is always the second.
