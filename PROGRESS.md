# PROGRESS

One row per component. **Status** is one of `not started` · `in progress` ·
`DONE` · `DONE, gate open` · `BLOCKED`. A component is never `DONE` on a
sub-session's report — only after the orchestrator re-ran the gate command
itself and read the real output.

_Last updated: 2026-08-30 · after the demo implementation pass._

> **The current state of the demo is `DEMO-IMPLEMENTATION-STATUS.md`, and how to
> run it is `DEMO-RUNBOOK.md`.** The component table further down describes the
> platform tier and is still accurate for it; it predates the tutor runtime,
> the starting assessment, the drawing engine and the rewards system, and those
> are not in it.

---

## 2026-08-30 — the tutor runtime, and three things that were not true

The platform tier was real and the teaching tier was not connected to it. Three
structural facts, each confirmed by reading the code rather than the docs:

1. **The child app decided correctness.** `games.tsx` called
   `onAnswer(id, choice.correct ? "correct" : "incorrect")` and the play screen
   celebrated before any round trip. The backend stored whatever `result` the
   client sent.
2. **The AI brain was orphaned.** `tutor_ai/loop.py::run_step` had zero callers.
   `ai_decisions` and `activity_outcomes` — migration 0013 — were written by
   nothing. The running planner was `ORDER BY intro_order LIMIT n`.
3. **A session was a manifest, not a loop**, so nothing could adapt inside one.

And a fourth: `loadSession()` fell back to a fully client-side session whenever
the API was slow, so a demo against a broken backend looked identical to a
working one and persisted nothing.

**What was built.** `app/modules/tutor/` — the runtime loop: evidence from
Postgres → the AI brain through the one gateway → `guard_decision` → the new
deterministic guardrail layer → an activity built from a closed contract →
authoritative evaluation → attempt → BKT/mastery fold → rewards → the next
decision. `app/modules/starting/` — the caregiver assessment that gives a new
child their own BKT priors. Migration `0014`. A drawing engine. Rewards.
Session summaries. An AI inspector. Four seeded children. A rebuilt child app.

**The mastery rule was broken and is fixed.** The accuracy guard demanded 1.102
accuracy at twenty flawless two-choice attempts — REVIEW-QUEUE #5 had measured
it; it made mastery unreachable for every child, not merely slow. Replaced with
an anytime-valid mixture martingale plus a lifetime accuracy floor. Flawless
independent play now reaches mastery at attempt 20 (2 choices) / 13 (3, 4); a
random tapper still never does, over 40 seeds × 500 attempts × 3 choice counts.

**Defects found only by running it.** `tutor_ai/audit.py` raised on its first
ever execution (`UUID()` on an asyncpg UUID). The brain's activity-type list
named four types of which the runtime implements one, so the deterministic
fallback tripped its own guardrail on every decision. `modality_accuracy` was
keyed on the wrong vocabulary, so "this child does better visually" was
permanently false. `NullSms` printed Arabic to a cp1252 console and made every
sign-in on Windows a 500. `/me` returned an empty name for every child. The
starting assessment 500'd on React's double-mounted effect. A session marched
through fourteen skills and repeated none; capped, it then locked onto one.

**Gates.** `just demo-check` — one command, one verdict. Coverage gate now
**PASS on 40 files** at 100 % branch. Six Playwright tests walk the critical
path in Chromium against the real API and the real database, and **Playwright
has now been executed** — the "NEVER EXECUTED" banner on the older specs still
applies to those specs.

**Environment.** Docker Desktop cannot be started on this machine without
administrator rights. PostgreSQL 16 + pgvector, Redis and MinIO were provisioned
in WSL2 on the ports `.env` already names, so nothing in the repository changed.
DEMO-RUNBOOK §2.

---

> ⚠️ **This file is behind the tree in one respect and it is worth knowing
> which.** The commit `a86234c` added four backend modules — `assessment`
> (router/service/repository), `play`, `chat` and `recommendation` — four
> migrations (`0008`–`0010`), four more mounted routers, and `app/core/wiring.py`
> (which closed the "503 … is not configured" defect on every `/progress/*` and
> `/voice/*` route). The component table below still describes the state before
> that. The rows for P05, P10 and P12–P14 in particular understate what exists.

---

## 2026-08-29 — the mastery loop, and two orphan modules connected

**`skill_states` and `mastery_events` had four readers and no writer.** Attempts
were stored, the dashboard counted sessions and minutes, and `p_known` never
moved — so no skill left `not_started` and nothing could reach `mastered`. Every
piece was built and tested at 100% branch coverage; nothing called any of them.
The only writer of either table in the repository was `app/ai/inspect.py`, the
`sanad rag demo` seeder.

Now wired, at session end, in `app/modules/learning/service.py`. It **runs
`tutor_ai/session.py`** rather than reimplementing the rule — which also makes
P08's orchestrator reachable code for the first time. `p_known` is recomputed
from the whole attempt history on every run (idempotent by construction);
`state` is seeded from the database, because `next_state` advances one rung per
evaluation by design. Decisions and rejected alternatives:
[`docs/adr/018-mastery-loop.md`](docs/adr/018-mastery-loop.md).

**Two migrations.** `0011` adds the thirteen `skill_states` columns docs/02 §6
specifies and 0008 omitted (0008 was built from one query's SELECT list).
**`0012` widens the primary key to `(child_id, skill_id, modality)` and is the
project's first deliberately destructive migration** — alone in its revision,
and it needs the `destructive-migration` label to deploy. `just guards` fails on
exactly that one line, which is the guard working, not a regression.

**`app/workers/jobs.py` now exists.** `schedule.py` had said "the job bodies live
in `app.workers.jobs`" since P11; the module did not, and neither did a runner.
Two of the nine jobs have bodies (`bkt_decay`, `rollup_rebuild`); the other seven
are absent from the registry and named in `UNBUILT` with what each is waiting
for, and `run_job` refuses them by name. Entrypoint: `just worker <job>`. Both
verified against the dev database. **No scheduler invokes them** — that needs
the platform cron in P15, which has never been deployed.

**BLOCKED.md's `ai_cannot_grant` item is closed.** Open since P07: the
application rule was tested and the database backstop never was. There is now a
test that inserts the exact row an AI verdict would need to promote a child on
its own authority and asserts Postgres rejects it by name.

**REVIEW-QUEUE #5 is confirmed on the real path.** A child answering 20/20
correctly, independently, on 20 separate days does **not** reach `mastered` —
the accuracy guard demands 1.102 at n = 20. #5 had already measured that
threshold in simulation; it now governs what a real family experiences.

Six integration tests against real Postgres, 24 new unit tests, 100% branch on
the new `domain/snapshot.py`. Two pre-existing breaks repaired on the way: the
`required-guardrail-layer` control fixture had never been updated for the two
chat decision points, and `test_recommendation_rag.py`'s `skill_states` upsert
named the old two-column key.

---

| # | Component | Status | Branch | Tests | Coverage | Gates open |
|---|---|---|---|---|---|---|
| P00 | Repository scaffold | **DONE** | `feat/p00-scaffold` | 40 | 96% line | — |
| P01 | C01 Identity & access | **DONE** (service layer) | `feat/p00-scaffold` | 87 | 98% service · 99% router | repository.py needs a DB |
| P02 | C02 Child profile & consent | **DONE** (service layer) | `feat/p00-scaffold` | 33 | 100% service · 100% gate | repository.py needs a DB |
| P03 | C15 Gateway + guardrails | **DONE, gate open** | `feat/p00-scaffold` | 121 | **100% branch** | red-team corpus (#7) |
| P04 | C03 Assessment engine | **DONE, gate open** | `feat/p00-scaffold` | 87 | **100% branch on domain/** | clinician verification (#4) |
| P05 | C04 PGEE AI orchestrator | **partial** | `feat/p00-scaffold` | — | — | graph/SSE not built — see below |
| P06 | C05 Content & curriculum | **DONE, gate open** | `feat/p00-scaffold` | 48 | **100% branch** | native-speaker sign-off (#6) |
| P07 | C06 Adaptive engine (BKT) | **DONE, gate open** | `feat/p00-scaffold` | 73 | **100% branch on domain/** | BKT parameters + the addition (#5) |
| P08 | C07 Tutor orchestrator | **DONE** | `feat/p00-scaffold` | 67 | **100% branch** | — |
| P09 | C08 Voice gateway | **DONE, gates open** | `feat/p00-scaffold` | 172 | **100% branch on domain/** | SLT corpus (#8) · calibration (#9) · voice talent (#10) · listening test (#11) |
| P10 | C09 Progress | **DONE** (service layer) | `feat/p00-scaffold` | 45 | **100% branch on domain/** | repository.py needs a DB |
| P11 | C10 Notifications | **DONE** (policy + send path) | `feat/p00-scaffold` | 47 | **100% branch on domain/** | DB-level dedupe unproven |
| P12 | C12 Caregiver app | **partial** | `feat/p00-scaffold` | 87 web | — | Playwright never run · no Storybook · no PWA · #1 |
| P13 | C13 Child app | **partial** | `feat/p00-scaffold` | (in the 87) | — | Playwright never run · OT review (#12) · real-device audio |
| P14 | C14 Clinician console | **partial** | `feat/p00-scaffold` | (in the 87) | — | no auth realm · no editors · no audit_log |
| P15 | Infrastructure & CI | **partial** | `feat/p00-scaffold` | 18 guards | — | never applied, never deployed, CI never run |

**`just test` is green end to end for the first time: 863 API tests passed, 0
failed**, then `COVERAGE GATE PASS: 30 critical file(s) at 100% branch
coverage`, 32 tooling tests and 87 web tests. The Docker daemon was recovered
(`com.docker.service` was stopped), migrations `0002`–`0006` applied cleanly on
their first ever run against real Postgres — partitioning and dedupe index
included — and the five integration tests that had never executed now pass 8/8.
**BLOCKED.md #1 is closed.**

**And running it end to end immediately found a real defect.** `POST /children`
returned 500: `relation "caregiver_child" does not exist`. docs/02 §3 specifies
that table, `identity/models.py` maps it, and `0003_children_consent` *mentions
it in a comment* while never creating it — so every child-scoped ownership check
was querying a table that did not exist. Invisible to 863 passing tests, because
`repository.py` had no database to run against. Fixed in
`0007_caregiver_child`, transcribed verbatim from docs/02 §3, as a new forward
migration rather than an edit to an applied one. After it the whole platform
walk works: OTP → RS256 token → `/me` → create child (mandatory-consent gate
correctly refusing first, in Arabic, as RFC 9457) → consent ledger → Arabic
stored byte-exact.

**One more gap the walk exposed:** all four `/progress/*` routes return 503
`Progress service is not configured` in any running instance —
`set_progress_service_factory` is called by tests and by nothing in `app/`.

What that did *not* do is write the tests that needed a database:
`progress/repository.py` is still at 0%, `children/` at 34%, `identity/` at 37%,
and the `ai_cannot_grant` database backstop, the export/erasure FK walk and the
Postgres-level notification dedupe proof are all still unwritten. They are now
possible rather than done.

The branch-coverage gate now reports **PASS on 30 files** at 100% branch
coverage — every `domain/` package plus `app/guardrails/`.

> **That number is new, and so is the gate actually running.** `tools/lint/
> coverage_gate.py` had two defects and had reported `SKIP` on every run since
> P00: it matched only files *named* `domain*` (so `domain/` packages — most of
> them — were invisible), and it matched on an `app/` path prefix that
> `coverage.xml` does not write, since paths there are relative to the `<source>`
> root. Both are fixed. Earlier PROGRESS entries claiming 100% branch coverage
> were reading the pytest terminal report by hand; they were correct, but the
> gate that was supposed to enforce them was not enforcing anything.

### Since P15 — a defect pass and the tooling that was missing

**A fourth scoring defect, fixed.** docs/04d §3 prices a vowel-length error at
0.15 and writes it as a substitution. That substitution cannot occur here:
unvowelised Arabic writes no short vowels, so a shortened vowel arrives as a
*deleted long vowel*, which `similarity.deletion_cost` priced as an ordinary
indel at 0.8 — 5.3× the documented price for the one class the document calls
"almost never meaningful". Stacked with one other expected process it moved a
child out of the accept band: راس /rAs/ produced as /rt/ scored 0.633, a
`retry`, against 0.850 at the documented costs.

Now priced at 0.15 when the deleted long vowel sits **between two consonants**
(CVC → CC), deletion only. Both restrictions were established by running the
62-pair corpus, not chosen: a cheap long-vowel *insertion* lets the aligner slide
unrelated strings together and pushed صابونة/ترابيزة from 0.464 to 0.557, across
the accept threshold. The six `vowel_shortening` rows move to 0.95–0.98; no
non-match row changes band. **Unreviewed by an SLT, like the closed-vocabulary
rule — REVIEW-QUEUE #8.**

**`just guards` ran four of the five guards.** `destructive_migration.py` was
added in P15 and wired into CI but not into the justfile, so a local `just
guards` reported green on a tree CI would reject. Fixed, with a comment saying
the two lists must match.

**`just up` — the whole stack, one command, one log stream.** `tools/dev/`:
a preflight that names every missing prerequisite *and what that absence breaks*
(never a silent degradation), containers, migrations, uvicorn and Next as child
processes, and every log line from all of them in one timestamped colour-coded
stream — structlog JSON re-rendered as prose, one line per HTTP request with a
correlatable request id, the raw stream teed to `logs/dev-<timestamp>.log`, and
a request summary on Ctrl-C. Runs and reports correctly with Docker down, which
is how it was developed. 18 tests over the two pure modules.

**`just voice-script` — the document REVIEW-QUEUE #10 was missing.** SETUP.md §4
said "script provided by the agent" and no script existed, which is part of why
the longest-lead item had not started. `tools/voice_render/recording_script.py`
assembles it from the repo's own curriculum, with a phonetic-coverage check that
can fail (all 26 phonemes are covered today) and a duration estimate that counts
takes. It reports that the curriculum yields ~15 minutes against a 20-minute
floor and says what the gap has to be filled with, rather than padding it with
invented Arabic. Carries a DO-NOT-RECORD banner while `seeds/curriculum.py`
`REVIEWED_BY` is empty. 12 tests.

**A defect in the web image, found without a daemon.** `apps/web/Dockerfile`
copies `.next/standalone` and runs `node apps/web/server.js`; `next.config.mjs`
never asked Next to emit a standalone build, so the image build would have
failed at the `COPY` — reading as a broken Dockerfile rather than a missing
config key. The config now emits standalone when `NEXT_OUTPUT=standalone`, which
the Dockerfile's build stage sets; gated on the env var because `next start`
refuses to serve a standalone build and an unconditional setting would break
every local production run. Both paths verified: the plain build feeds
`next start`, and the gated build lands `server.js` at exactly the path the
`CMD` expects. **`pnpm --filter @sanad/web build` had also never been run** — it
succeeds, 13 routes.

**`just up-prod` — the stack in its deployed shape.** Production settings from a
generated `.env.production-local` (`just prod-env`: RS256 keypair, real pepper
and invite secret, because `_check_production_secrets` correctly refuses the
`local-dev-` placeholders), no reloader, two uvicorn workers, Next serving a
build, `/docs` correctly 404. Verified running; a multi-line PEM round-trips
through a quoted `.env` value and RS256 signs and verifies. One bug found doing
it: `uv run --env-file` mangles an absolute path when the repo path contains
spaces (`E:\Summer Academy - DELL\…` came back as `DELLRevamped.env…`), so the
runner passes the relative form the `migrate-test` recipe already used.

**`just` did not work on Windows at all.** Every recipe failed with `could not
find the shell 'sh'` — just defaults to `sh`, and Git Bash's `sh.exe` is not on
PATH by default. Earlier sessions ran recipes from a shell that happened to have
it, so this had never surfaced. The justfile now sets `windows-shell` to
PowerShell, verified for exit-code propagation, early exit on a failing line,
and not mistaking stderr output for failure. `just --list`, `guards`, `lint`,
`test-quick`, `voice-script`, `prod-env` and `up` all re-run green from a plain
PowerShell prompt.

**Procedures for the two urgent gates.** `docs/setup/` — 01 the Nour voice
(casting brief, the vowelisation dependency, the script, a release checklist,
the listening test, and the honest note that `renderer.py` does not exist yet),
02 Groq and the two model licences (the key is ten minutes; the DPA is the thing
that actually blocks, and doing the first and calling #13 closed is the failure
mode), 03 everything else, and **04 running it in its deployed shape** — which
also states the ceiling plainly: only four routers are mounted (identity,
children, voice, progress), there are no content/assessment/learning/session
tables in any migration, and `just seed` correctly exits 1 because there is
nowhere to put the curriculum. The platform tier runs end to end; the learning
and assessment tiers have domain logic at 100% branch coverage and no HTTP
surface or persistence yet.

---

### What P05 is missing, stated plainly

P05 asks for a LangGraph session with `AsyncPostgresSaver` checkpointing and an
SSE endpoint with `Last-Event-ID` replay. **Neither is built.** What exists is
everything P05 depends on: the gateway with fixture replay, the guardrail chain,
the assessment engine, and the deterministic fallback for every decision point.
The graph itself is wiring over those, and it needs a live Postgres for the
checkpointer — which is the blocker below.

The P08 equivalent *is* built, because the tutor session state machine is pure
and needed no checkpointer to be exercised.

---

---

## P09–P15 — what was built, and what was not

The honest summary is that **P09, P10 and P11 are complete to the same standard
as P01–P08, and P12–P15 are partial.** The dividing line is not effort; it is
what can be *verified* on this machine. The backend components are pure logic
over tested domain code. The three client apps and the whole of infrastructure
are things whose acceptance criteria are about something *happening* — a browser
rendering, a container building, an `apply` running — and none of that can
happen here.

### P09 — C08 voice gateway · DONE, gates open

Built to docs/04d as revised by docs/12 §Δ2: `normalize_ar`, an Egyptian g2p
rule table, the weighted-Levenshtein scorer with the docs/04d cost matrix, three
verdicts, accept-on-effort, the caregiver override, the Qwen → Groq Whisper →
caregiver-confirmation ladder, upload validation by magic bytes, unconditional
audio deletion, the offline render plan and publish gate, and a fine-tune
exporter that refuses unconsented rows.

**Three findings from the 60-pair corpus**, all recorded in
`docs/adr/011-voice-scoring.md` rather than reconciled away:

1. **A real false accept at exactly the threshold.** باب heard as شباك scores
   0.550, and 0.550 accepts. Fixed with a closed-vocabulary rule — an ASR
   hypothesis that exactly matches another taught word is capped at `retry` —
   not by moving the threshold, which would have rejected the substitutions the
   design exists to accept. **The rule is not in docs/04d and no therapist has
   seen it.** → REVIEW-QUEUE #8
2. **The `vowel length 0.15` class in docs/04d is unreachable.** Unvowelised
   Arabic writes no short vowels, so a shortened vowel arrives as a deleted long
   vowel priced at 0.8. The constant is right; the path to it does not exist.
3. **Two corpus rows had wrong hand-arithmetic.** Metathesis inside a cluster
   costs 1.1, not 2.0, because a cluster-internal deletion is cheap. The
   implementation was right and my derivation was naive.

**Verified:** attempt 2 is accepted on pure noise · a genuine non-match is never
accepted · all 88 skills are reachable receptively without microphone consent ·
audio leaves neither a temp file nor an S3 object without `voice_retention` ·
`app.modules.voice` cannot import `app.ai` (asserted by parsing imports, not by
spying on calls).

**Not built:** the pgvector per-child reference model; ffmpeg transcoding (the
validator sniffs the container, nothing re-encodes); the actual VoxCPM2 render.

### P10 — C09 progress · DONE (service layer)

One `compute()` serves both rollup paths, so the nightly backstop can genuinely
disagree with the incremental path. A 30-session synthetic history — including
same-day sessions and a gap week, the two shapes where a delta-based path
diverges — runs through both and diffs to zero.

The three product rules from docs/04a §C09 live in `domain/views.py`: no trend
under three points, no norm on any dashboard (checked over the *entire* OpenAPI
document), and a regression that always carries exactly three activities or is
not surfaced at all.

**Not verified:** `repository.py` is 0% covered. Migration `0005` has never run.

### P11 — C10 notifications · DONE (policy + send path)

One `decide()` gate that every send passes through, checking content → cap →
quiet hours in that order. Ten eligible notifications in a week deliver exactly
three. A 22:00 notification is delivered at 08:00, not dropped. `pgee_due` fires
at 180, 194 and 208 days and then never again, over a 250-day simulation.
Egypt's DST is tested in both directions, and there is a guard test asserting the
tz database on the machine actually has Egyptian DST rules — without it the DST
tests would pass vacuously.

**Not verified:** the database-level dedupe. docs/10 T11 §10 asks for proof that
*Postgres* rejects a duplicate; what exists is an assertion about the DDL text,
which is a weaker claim and is labelled as one in the test.

### P12/P13/P14 — the three clients · PARTIAL

**Playwright has never run.** No browser binary is installed and CI has never
executed a job. Every spec file opens with a `NEVER EXECUTED` banner.

So the interaction contract was moved into TypeScript modules with Vitest
coverage — `lib/interaction.ts`, `lib/prompt-ladder.ts`, `lib/progress-range.ts`,
`lib/outbox.ts`, `lib/contrast.ts`, `lib/console-access.ts` — and 87 tests pass
against them. That covers the touch-target arithmetic, the ladder terminating in
a success at every legal wait time, monotonic narrowing under adversarial
estimates, a simulated 30-second dropout losing zero attempts and creating zero
duplicates, contrast measured over the shipped stylesheet, and the console role
matrix walked exhaustively.

**A real defect found this way:** `globals.css` claimed every foreground/
background pair met 7:1. Measured, `--c-practising` is **3.26:1** and
`--c-resting` is **3.58:1** on white. Both are fine as a skill-map swatch (WCAG
2.2 SC 1.4.11 asks 3:1 of a non-text indicator) and neither is usable as a word,
so the pair list now separates the two uses and two text-safe tokens were added.

**A document disagreement, resolved on my own authority:** docs/04e §C13 says
touch targets are ≥ 80px; docs/06 §5 and docs/09 P13 say ≥ 88px. I used 88 and
recorded it at the constant. → REVIEW-QUEUE #12

`next build` succeeds: 13 routes, 106 kB shared JS, largest route 125 kB first
load. eslint, stylelint and `tsc --noEmit` are all clean.

**Not built:** Storybook with LTR and RTL stories (a stated docs/06 §8
requirement, unmet); the PWA layer; the report route; the console auth realm and
its editors; `audit_log`; the Zustand/IndexedDB/Cache-API layer in the child app;
four of the five activity renderers.

### P15 — infrastructure · PARTIAL

Written: production Dockerfiles for both services, Terraform modules and two
environments, the deploy workflow with blue/green and a 10-minute bake, the
Lighthouse budgets as hard `error` assertions, six runbooks, and the CI jobs that
were stubs after P00 (e2e, perf, Trivy).

**Genuinely verified: exactly one thing** — a fifth CI guard,
`destructive_migration.py`, with a violation fixture and a control fixture, and
`test_guards.py` proving it fires on one and stays quiet on the other. It exists
because migrations run *before* the new tasks start, so during the bake the old
code serves traffic against the new schema, and a `DROP COLUMN` is a 500 on every
request that touches the table from a deploy that has not technically failed.

**Everything else in P15 is unexecuted.** `terraform validate` has not run —
there are no provider plugins on this machine. No image has been built. CI has
never run. There is no AWS account, no registry, no OIDC role, and no remote.
Every one of docs/09 P15's acceptance criteria — apply from zero, automatic
rollback, the RPO/RTO restore drill, kill switches under load, Trivy on a built
image, gitleaks over full history — is **outstanding**.

---
## ⚠️ The Docker daemon on this machine stopped mid-session and did not recover

This is the single most important caveat in this file.

`docker info` began hanging indefinitely partway through P01 and never came back,
through a full Docker Desktop restart and a `wsl --shutdown`. Consequently:

| What | State |
|---|---|
| Migrations `0002`–`0004` | **Never executed.** They are written; only `0001` has ever run against a real Postgres. |
| `repository.py` (both modules) | ~35% covered. Every line is SQL and needs a database. |
| `tests/integration/` | Cannot run. Correctly marked `integration`. |
| The `ai_cannot_grant` CHECK constraint | **Not yet asserted against the database.** P07 requires executing raw SQL to prove an AI verdict cannot promote a child. The application-layer rule is tested; the database-level backstop is not. |
| Erasure / export completeness | Not testable without a DB. |

Everything above is *written* and lints and type-checks. None of it has touched
Postgres. When the daemon returns, `just migrate && just migrate-test && just test`
is the first thing to run, and I would not trust the DDL until it has.

---

## Stage gates

| Stage | Components | State |
|---|---|---|
| 1 — Spine | P00, P01, P02, P15 | P00/P01/P02 built; **P15 written but never executed**; DB-backed tests blocked |
| 2 — Assessment, no AI | P04 | Built, 100% branch. **Gate needs a clinician (#4).** |
| 3 — Learning, no AI | P06, P07 | Built. Random-tapper test green at 1000 sims. **Gates #5, #6.** |
| 4 — AI layer | P03, P05, P08 | P03/P08 built; **P05 graph + SSE outstanding**. Gate #7. |
| 5 — Voice, clients, ops | P09–P14 | P09/P10/P11 built; P12/P13/P14 partial and **never run in a browser**. Gates #8–#13. |

**No stage gate has been crossed.** Stages 2 and 3 were required to produce a
working product with zero AI code written; that ordering was followed — P04, P06
and P07 were built and fully tested before P03 was started.

---

## P00 — Repository scaffold & shared foundations · DONE

**Branch:** `feat/p00-scaffold` · **ADR:** [`docs/adr/001-stack.md`](docs/adr/001-stack.md)

### Acceptance criteria, verified

| Criterion | Result | Command / evidence |
|---|---|---|
| `just bootstrap && just dev` brings up api :8000 and web :3000 | **PASS** (with one caveat) | `just dev` verified end to end: turbo runs `@sanad/api:dev` and `@sanad/web:dev` together; `:8000/health` 200, `:8000/health/ready` 200, and `/home`, `/play`, `/console` all 200. **Caveat:** not run from a genuinely clean clone — there is no git remote yet. |
| `GET /health` returns 200 with no database dependency | **PASS** | With Redis stopped: `{"status":"ok","version":"0.1.0"}` HTTP 200 |
| `GET /health/ready` reports db, redis and s3 individually | **PASS** | Healthy: `{"status":"ok","checks":{"db":{"status":"ok"},"redis":{"status":"ok"},"s3":{"status":"ok"}}}` 200. Redis stopped: `{"status":"degraded","checks":{"redis":{"status":"error","reason":"TimeoutError"}}}` 503 |
| Unhandled exception → valid RFC 9457 with `message_ar`, never a stack trace | **PASS** | `tests/unit/test_health_and_errors.py::test_unhandled_exception_is_problem_details` asserts 500, `application/problem+json`, `message_ar` present, and that neither `ValueError`, the exception text, nor `Traceback` appears in the body |
| `just lint` passes: ruff, mypy --strict, eslint, stylelint | **PASS** | `ruff check` All checks passed · `ruff format --check` 25 files already formatted · `mypy --strict app` Success: no issues found in 16 source files · `tsc --noEmit` exit 0 · `stylelint` exit 0 |
| stylelint demonstrably fails on `margin-left: 4px` | **PASS** | `tools/guards/fixtures/physical-properties.css.fixture` → exit 2, 6 errors, each naming the logical replacement. Control fixture → exit 0. Asserted by `tools/guards/test_guards.py::test_stylelint_bans_physical_properties` |
| A missing required env var causes a clear startup failure naming the variable | **PASS** | Observed for real when alembic ran from the wrong directory: `ConfigurationError: Sanad API cannot start … SANAD_DATABASE_URL: Field required …`. Asserted by `test_config.py::test_missing_required_variable_names_it` |
| Web renders RTL, Arabic at 17px/1.9, no layout shift | **PASS** | In-browser: `dir="rtl"`, `lang="ar-EG"`, `font-size 17px`, `line-height 32.3px` (ratio 1.90), all four IBM Plex Sans Arabic faces `loaded`, **cumulative layout shift 0** |

### Additionally delivered beyond the prompt

- All four CI guard checks **fully implemented**, not stubbed (P00 permitted stubs).
- A violation fixture *and* a control fixture per guard, with
  `tools/guards/test_guards.py` asserting each fires correctly — **10/10 passing**.
- `tools/lint/banned_terms.py` (docs/06 §3 copy guidelines) and
  `tools/lint/coverage_gate.py` (100% branch on `domain/` + `guardrails/`).
- Migration 0001 is checked against `docs/02` §2 by a test that parses the design
  document, so the 19 enum types cannot drift from the spec.
- The Tailwind preset and `globals.css` are checked against `docs/06` §2 the same way.

### Last verified commands

```
services/api $ uv run pytest -q                        24 passed
services/api $ uv run pytest ../../tools/guards/test_guards.py    10 passed
services/api $ uv run ruff check .                     All checks passed!
services/api $ uv run ruff format --check .            25 files already formatted
services/api $ uv run mypy --strict app                Success: no issues found in 16 source files
services/api $ uv run alembic upgrade head             0001_enum_types applied
apps/web     $ pnpm exec tsc --noEmit                  exit 0
apps/web     $ pnpm exec vitest run                    6 passed
apps/web     $ pnpm exec next build                    5 routes, compiled successfully
repo root    $ pnpm exec stylelint "apps/**/*.css"     exit 0
repo root    $ python tools/lint/banned_terms.py       BANNED-TERMS PASS
```

Database state confirmed directly: 19 enum types with the documented value
counts, plus `pgcrypto` and `vector` extensions.

### Coverage

| Module | Line | Branch |
|---|---|---|
| `app/core/config.py` | 94% | |
| `app/core/db.py` | 100% | |
| `app/core/errors.py` | 95% | |
| `app/core/logging.py` | 96% | |
| `app/core/middleware.py` | 100% | |
| `app/core/otel.py` | 91% | |
| `app/core/redis.py` | 100% | |
| `app/core/storage.py` | 100% | |
| `app/main.py` | 98% | |
| **TOTAL** | **96%** | 36/42 branches |

CI gate is 85% overall — met. The 100%-branch gate applies to
`app/modules/*/domain*` and `app/guardrails/`, neither of which exists yet;
`coverage_gate.py` reports SKIP and names P02/P03 as the activating prompts.

### Not verified — stated plainly

1. **`just bootstrap` from a genuinely clean clone.** There is no git remote, so
   a true clean-clone run is not possible yet. Every step was run individually on
   this checkout and passed. The first real test of this is the first clone.
2. **The GitHub Actions workflow has never executed.** The YAML parses and the
   job graph is correct, but no runner has run it. The MinIO-as-a-step approach
   and the `psql`-based test-database creation are untested on `ubuntu-latest`.
3. **`just seed` and `just eval` exit 1 by design** with a message naming the
   P-prompt that will implement them. They are not stubbed to pass.
