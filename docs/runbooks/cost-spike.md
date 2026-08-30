# Cost spike

## Confirm

1. `/console/cost?group_by=child` — one child, or the platform?
2. `/console/cost?group_by=day` with the provider dimension (docs/12 §Δ3). A
   spike concentrated on Anthropic is assessment volume; on Groq it is play
   sessions.
3. Check the cache read ratio on the AI-health dashboard. **Below 60% is the
   signal that matters.** A collapsed cache ratio means dynamic text has entered
   a prompt prefix — a cost problem, and more often than not a sign that
   something identifying is now being sent on every call.

## Do

**One child, high spend.** The per-child budget guard is already doing its job:
the hard limit at $0.60/day returns `budget_exceeded` and the caller runs its
deterministic path. Confirm that child sessions still complete, then find out
why. A caregiver re-running an assessment repeatedly is a UX problem wearing a
cost problem as a disguise.

**Platform-wide.** Trip the highest-volume, lowest-stakes decision points first,
at `/console/flags`, in this order:

1. `tutor_summary` — four friendly lines; the template is fine.
2. `pgee_next_item` — the engine own choice is the ground truth anyway.
3. `tutor_plan` — deterministic ordering already exists.

Do **not** trip `safety_classify`. It fails closed, and its failure mode is a
human reading an escalation that did not need one. That is the right way round.

**Cache ratio below 60%.** This is an incident, not a tuning task. Find the
prompt whose prefix changed, revert it (see bad-prompt.md), and check whether
the dynamic content that got in was pseudonymised.

## After

If the spike was real demand rather than a bug, the routing table in docs/12 §2
is the lever. Changing it requires running `interpret_ar.jsonl` against the
candidate model first; the gate is ≥95% exact match with 100% red-flag recall,
and it is a gate rather than a guideline.
