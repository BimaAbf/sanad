# ADR 018 — Closing the mastery loop

**Status:** accepted · **Date:** 2026-08-29 · **Supersedes:** nothing

## Context

`skill_states` and `mastery_events` had four readers and no writer. `attempts`
had been stored since the play module existed; `learning/domain/bkt.py`,
`learning/domain/mastery.py`, `learning/domain/scheduling.py` and
`tutor_ai/session.py` were all built, tested, and at 100% branch coverage; and
nothing in `app/` called any of them.

The observable consequence: a child could play indefinitely and `p_known` never
moved, no skill left `not_started`, and nothing could reach `mastered`. The
caregiver dashboard counted sessions and minutes correctly, which is what made
it survive — the product looked like it was working.

The only writer of either table in the whole repository was `app/ai/inspect.py`,
the `sanad rag demo` seeder, which inserts them with raw SQL so the retrieval
path has something to retrieve.

## Decisions

### 1. Run `tutor_ai/session.py` rather than write a second implementation

The mastery rule is the place in this product where being wrong is silent and
lands in a child's clinical record. P08 already folds BKT over attempts, tracks
distinct days and delayed passes, applies `mastery_rule`, clamps an AI verdict
through `enforce_conservatism`, and decides the transition — with 67 tests
behind it.

`learning/service.py` therefore loads state, hands it to `session.py`, and
persists what comes back. Rejected: re-deriving the fold in a repository-facing
service, which would have produced two implementations of one rule and no way to
know which one a given number came from.

A side effect worth naming: `tutor_ai` was unreachable code before this. It is
now on the request path, which is a better answer to "why is that module here"
than deleting it or leaving it dangling.

### 2. Recompute `p_known` from the full history; seed `state` from the database

Two quantities that look similar and are not:

* `p_known` is a **function of the attempts**. It is recomputed from `BktState()`
  over the whole history on every run, so it is idempotent — a replayed outbox,
  a retried request or a backfill all produce the same posterior. An incremental
  update would make a clinical number depend on how many times the code
  happened to execute.
* `state` is a **history of decisions**. `next_state` advances one rung per
  evaluation by design, so it is seeded from the stored value. A from-scratch
  replay would collapse a child's whole journey into a single step each time.

The cost is a full history read per skill per session end. At the volumes this
product will see (a handful of skills per session, tens of attempts per skill)
that is cheaper than the class of bug it removes.

### 3. Apply the loop at session end, not per attempt

Attempts arrive one at a time online and in a drained batch after a dropout.
Folding at session end means both paths produce identical state, and the
recompute happens once rather than once per POST. It also puts the write after
`session_end` and the rollup, so the whole of a session's effect lands together.

### 4. `skill_states` completed to docs/02 §6, in two migrations

0008 built the table from the SELECT list of one query — eight of the twenty-one
columns docs/02 §6 specifies — because it was written to stop the skills page
erroring, and that is all it needed to do. The BKT parameters, the
spaced-repetition fields and the mastery bookkeeping were all absent.

* **0011** adds the thirteen missing columns, verbatim from docs/02 §6. Additive.
* **0012** widens the primary key from `(child_id, skill_id)` to
  `(child_id, skill_id, modality)`. **Destructive**, alone in its revision,
  and it needs the `destructive-migration` label to ship.

The split is what GUARD 5's own failure message recommends. Two divergences from
docs/02 are deliberate and recorded in 0011's docstring: `p_known` keeps 0008's
`double precision` (a column-type rewrite is what the guard exists to stop, and
the precision of a Bayesian posterior is a storage choice), and `due_at` stays
nullable (NULL already means "no review scheduled", which is true for a skill
never practised). 0008's `DEFAULT 0.0` on `p_known` is corrected to `0.15`,
which is `bkt.P_L0` and what every other file in the project agrees on.

**Why widen the key now.** A narrower key is not a smaller version of the right
one — it makes the right one unrepresentable. A child cannot hold a receptive
and an expressive state for the same skill. Every other table already threads
modality through (`attempts`, `mastery_events`, and the `(skill_id, modality)`
keys `tutor_ai` has used since P08); this table was the one place the concept
went missing. It has not bitten only because the voice tier has no client. There
are twelve rows in the table, on the only database it has ever existed on, all
written by the demo seeder. The cost of this change increases monotonically from
here.

### 5. Every transition writes a `mastery_events` row

`ai_cannot_grant` is a CHECK on `mastery_events`, not on `skill_states`. A
transition that updated the current state without recording the event would
route around the one constraint P07 asked the database to enforce.
`rule_satisfied` is written from the **deterministic** verdict and never the
AI's, because that is the column the constraint tests.

### 6. Unbuilt jobs are absent from the registry, not stubbed

`workers/schedule.py` declared nine cron jobs and `workers/jobs.py` did not
exist. Two of the nine have dependencies that are built (`bkt_decay`,
`rollup_rebuild`); the other seven do not.

Those seven are absent from `JOB_BODIES` and named in `UNBUILT` with what each
is waiting for. `run_job` refuses them by name. A body that quietly does nothing
would be worse than no body at all, because it looks like it ran — and this is
the same convention `cli.py` already uses for `just seed` and `just eval`.

`test_worker_jobs.py::test_every_declared_job_is_either_built_or_named` makes
the third state — declared, unbuilt, and unexplained — a test failure.

## Consequences

**Proven against real Postgres** (`tests/integration/test_assessment_and_play.py`):
a finished session writes a skill state whose `p_known` has moved off the prior;
the transition is recorded as a `mastery_event` naming its session; re-ending a
session does not move `p_known`; a child who genuinely learns reaches
`mastered`; an alternating tapper does not, while its `p_known` saturates above
0.9; and Postgres itself rejects a `mastered` transition with
`rule_satisfied = false`.

**That last one closes a gap open since P07.** BLOCKED.md has carried "the
`ai_cannot_grant` CHECK constraint is not yet asserted against the database"
since the Docker daemon failed. It is asserted now.

**REVIEW-QUEUE #5 is now confirmed through the real path.** #5 already measured,
in simulation, that a perfectly accurate child needs ~30 attempts at two choices
before the accuracy guard can be satisfied. Writing the positive control here
hit exactly that: a twenty-attempt flawless run does not reach `mastered`,
because at n = 20 the required accuracy is 1.102 — above 1.0, so no child can
achieve it. The test uses forty and says why.

This is corroboration, not a new finding: the same number, arrived at
independently over HTTP and Postgres rather than in a simulation loop. It does
mean the cost #5 asks a clinician to rule on is now a property of the running
product rather than of a model of it. → REVIEW-QUEUE #5

**Open.** `bkt_decay` and `rollup_rebuild` have bodies and a CLI entrypoint
(`sanad worker <job>`, `just worker <job>`) and **no scheduler invokes them** —
that needs the platform cron in P15, which has never been deployed. The seven
unbuilt jobs are blocked on the notification send path, the report route, the
escalations table, the TTS renderer and per-child cost accounting, none of which
exist.
