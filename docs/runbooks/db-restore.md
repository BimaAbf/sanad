# Database restore

Targets from docs/08 §8: **RPO ≤ 5 minutes, RTO ≤ 1 hour.** PITR is what
delivers the RPO; nightly snapshots alone would put it at 24 hours.

⚠️ **Never rehearsed.** docs/09 P15 requires a real restore into a scratch
environment with measured timings, and that has not happened. Until it does,
treat the RTO as an estimate rather than a commitment.

## Restore

1. **Stop writes.** Scale the api and worker services to zero. A restore racing
   live traffic produces a database nobody can reason about afterwards.
2. Pick the target second. For corruption this is the moment *before* the bad
   deploy or the bad migration — read it off the deploy log, not off the alarm
   time, which is always later.
3. `aws rds restore-db-instance-to-point-in-time` into a NEW identifier. Never
   restore over the original: it is the only copy of anything the restore turns
   out to have missed.
4. Run the consistency check. It verifies that every `attempts` row has a
   session, every `assessment_responses` row has an item, and that no
   `mastery_events` row has `to_state = 'mastered'` with `rule_satisfied =
   false` — the `ai_cannot_grant` constraint, re-checked as data rather than
   trusted as DDL.
5. Repoint the application, scale back up, watch `/health/ready`.
6. Replay the ARQ dead-letter queue. Rollups are idempotent upserts, so a replay
   cannot double-count; that is what makes this step safe rather than delicate.

## The quarterly drill

The same steps, into a scratch environment, with a stopwatch. Record both:

- **RPO** — the gap between the last committed transaction and the restore
  point.
- **RTO** — wall clock from "decision to restore" to "`/health/ready` returns
  200", **including** the consistency check. An RTO measured without it is
  measuring the wrong thing, because a database that is up and wrong is not a
  recovered database.

Write both numbers into PROGRESS.md. A drill whose numbers nobody recorded did
not happen.
