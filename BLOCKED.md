# BLOCKED

Anything the orchestrator cannot proceed on, and what would unblock it.

_Last updated: 2026-08-29 · after P09–P15, then a defect-and-tooling pass_

> **#1 is closed.** The Docker daemon is running, all six migrations have been
> applied, and `just test` is green end to end for the first time. There is no
> hard blocker left — #2–#5 change what results *mean*, or need a person or an
> account.

---

## 1. ~~The Docker daemon~~ — RESOLVED 2026-08-29

**Was the only hard blocker. It is closed.**

`com.docker.service` was `StartMode: Manual`, `State: Stopped` — that service is
what creates the named pipe, which is why `docker info` reported the pipe absent
rather than a wedged daemon. `Start-Service com.docker.service` from an elevated
PowerShell, then Docker Desktop, restored it. Procedure:
`docs/setup/04-running-it-deployed.md` §1.

**One real defect had to be fixed on the way.** `docker compose up -d --wait`
failed with `container sanad-minio-init-1 exited (0)` while every container was
healthy: `--wait` treats *any* container that exits as a failed start, including
a one-shot bucket-creator that exits 0 having done its job. That broke both
`just bootstrap` and `just up`. `minio-init` now carries `profiles: ["init"]` so
it is out of the default `up`, and `bootstrap` runs it explicitly with
`docker compose run --rm minio-init`, which waits for completion and returns its
exit code.

### What ran, and what it proved

| | |
|---|---|
| Migrations `0002`–`0006` | ✅ **applied cleanly on the first attempt** — including the monthly RANGE partitioning of `events` and the notification dedupe index. 17 relations in both `sanad` and `sanad_test`. This was the largest open risk in the project: DDL transcribed from `docs/02` and never executed. |
| `tests/integration/test_stack.py` | ✅ **8/8 pass** against the real stack. The five that had never run now do. |
| `just test` | ✅ **863 passed, 0 failed**, then `COVERAGE GATE PASS: 30 critical file(s) at 100% branch coverage`, 32 tooling tests, 87 web tests. **Green for the first time in the project's history.** |

### And it immediately found a real defect

The first end-to-end request after the daemon came back — `POST /children` —
returned **500: `relation "caregiver_child" does not exist`**.

`docs/02 §3` specifies `CREATE TABLE caregiver_child`.
`app.modules.identity.models.CaregiverChild` maps it. `0003_children_consent`
*mentions it in a comment* — "the DDL there has caregiver_child but nowhere to
hold a pending invitation" — and never creates it. Every child-scoped route
depends on it for the ownership check.

Fixed in `0007_caregiver_child`, transcribed verbatim from docs/02 §3, as a new
forward migration rather than an edit to `0003` (a migration that has been
applied anywhere is history). After it: `POST /children` returns 201,
`GET /me` lists the child with `role: owner`, the consent ledger reads back with
its Arabic wording, and Arabic round-trips to the database byte-exact.

**This is precisely what BLOCKED.md predicted and could not check.** One
transcription omission, invisible to 863 passing tests, in the DDL nobody had
ever executed.

### What it unblocked but did NOT do

Having a database does not write the tests that needed one. All of these are now
*possible* and remain *outstanding*:

| Outstanding | State |
|---|---|
| `identity/repository.py` | 37% — pure SQL, still barely exercised |
| `children/repository.py` | 34% |
| `progress/repository.py` | **0%** — every line is SQL |
| The progress routes | Unreachable in a running instance: `set_progress_service_factory` is never called outside tests, so all four `/progress/*` routes return 503 `Progress service is not configured`. Wiring it is one line; doing so without tests would put untested SQL in the request path. |
| `GET /me` child names | Hard-coded `display_name=""` with a comment saying the children module will fill it. That module now exists. |
| The `ai_cannot_grant` CHECK constraint | P07 wants raw SQL proving an AI verdict cannot promote a child to `mastered`. The application rule is tested; the database backstop still is not. |
| P05's LangGraph checkpointer | `AsyncPostgresSaver` now has a Postgres to point at. Nothing is built yet. |
| Export and erasure completeness | P02 wants a walk of every foreign key to `children`. Not written. |
| The notification dedupe guarantee | docs/10 T11 §10 wants proof that **Postgres** rejects a duplicate. What exists is an assertion about the DDL text. |
| Both Docker images | Never built. The Trivy gate has still never scanned anything. `docs/setup/04` §8. |

---

## 2. Sub-session delegation is off, and it changes what P04 and P07 are worth

Not blocking — flagged because it changes how much the P04 and P07 results mean.

`ORCHESTRATOR.md` §5 makes two *independent* sessions mandatory for those two
components: one writes the engine, one writes the expectations, neither sees the
other. This session has no sub-agent capability enabled, so the same author
produced both sides.

The substitute used was to derive the expectations from the written rules and
record them **before** implementing. The engine then agreed on the first run.
That is meaningful evidence — but it is not the protocol, and it is recorded as
such in `REVIEW-QUEUE.md` #4 and in the golden-case file itself.

---

---

## 3. No browser, so Playwright has never run

Not blocking further development; it blocks every acceptance criterion in
docs/10 T12 and T13 that is phrased as a browser assertion.

There is no Playwright browser binary on this machine and `playwright install`
was not run — it is a ~400 MB download that would not have been usable in CI
anyway, since CI has also never run.

**What it blocks:**

| Blocked | Why |
|---|---|
| axe-core on every route | Needs a rendered DOM |
| Touch-target bounding boxes at 320px | Needs layout |
| The 200% text-zoom check | Needs layout |
| The no-physical-CSS check over the *built* stylesheet | Needs a served build |
| The 500-interaction fuzz | Needs an event loop |
| Lighthouse budgets | Needs a browser and a server |

**Mitigation, and its limit.** Everything that could be moved into a pure module
was: `apps/web/src/lib/*.ts` with 87 Vitest tests covering the touch-target
arithmetic, the ladder, monotonic narrowing, the outbox, contrast over the
shipped stylesheet, and the console role matrix. That found a real contrast
defect the browser tests would also have found.

It does not cover anything about *layout*. A component can satisfy every
constant in `interaction.ts` and still render an 88px button clipped to 40px by
a parent container, and nothing here would notice.

**What would unblock it:** `pnpm exec playwright install --with-deps chromium`,
then `pnpm exec playwright test`. Expect failures — several specs target routes
that are stubs (the report screen, the console child-record page).

---

## 4. No cloud account, so none of P15 has been executed

`terraform validate` has not been run: the provider plugins have never been
downloaded. `terraform plan` and `apply` need an AWS account that does not
exist. The deploy workflow needs a registry and an OIDC role. `gitleaks clean
over full history` needs a remote, and there is no git remote.

**What it blocks:** every acceptance criterion in docs/09 P15 and docs/10 T15
§7–§13, without exception.

**What would unblock it:** an AWS (or Hetzner + Cloudflare) account and a state
backend. Then, in order: `terraform validate`, `plan` against staging, `apply`,
then the three drills — the deliberately-broken-deploy rollback, the restore
drill with real RPO/RTO timings, and the kill switches under simulated load.

I would not trust the Terraform until `validate` has run. Module wiring is
exactly the kind of thing that reads correctly and does not resolve.

---

## 5. Six ADRs are referenced by the code and do not exist

Not blocking. A documentation debt from P01–P08 that I found while writing
011–017 and am recording rather than quietly filling in.

`docs/adr/` contains `001-stack.md` and, from this session, `011`–`017`. These
are referenced from source comments and do not exist:

| Referenced ADR | Referenced from |
|---|---|
| `002-auth.md` | identity module |
| `003-consent-model.md` | migration 0004, children module |
| `006-scoring-rules.md` | assessment domain |
| `008-curriculum.md` | curriculum seed |
| `009-bkt-parameters.md` | `learning/domain/bkt.py` — and this is the one that matters |
| `010-tutor-orchestration.md` | tutor session |

**Why I did not write them.** An ADR records a decision *someone made*. Writing
002–010 now would be me reconstructing, from code comments, decisions made in an
earlier session — producing a document that reads like a record and is actually
a guess. `009-bkt-parameters.md` is the sharpest case: `bkt.py` says "none of
them is yet evidence-based" and points at an ADR for the reasoning, and inventing
that reasoning after the fact would be worse than the dangling reference.

**What would unblock it:** whoever made those calls writes them, or accepts that
the code comments are the record and the references get removed.

## Watch list — not blocking yet

| Item | Becomes blocking at | Tracked in |
|---|---|---|
| Named clinician (O2) | Stage 2 gate | REVIEW-QUEUE #3, #4, #5 |
| Portage licensing (O1) | PGEE go-live | REVIEW-QUEUE #2 |
| Independent red-teamer | Stage 4 gate | REVIEW-QUEUE #7 |
| Native Egyptian Arabic speaker | Stage 3 and Stage 5 | REVIEW-QUEUE #1, #6 |
| Voice talent booking | Stage 5, long lead time | SETUP §3 |
| `ANTHROPIC_API_KEY` | Gate 4, and the empirical half of the prompt-cache guard | SETUP §2 |
| A git remote | Whenever `just bootstrap` is first run from a clean clone | PROGRESS.md |
| A CI run | The workflow has still never executed on a runner | PROGRESS.md |
| Nour voice talent | **Now** — longest lead time in the project | REVIEW-QUEUE #10 · procedure: `docs/setup/01-nour-voice.md` |
| Speech-language therapist | Stage 5 voice gate | REVIEW-QUEUE #8, #9 |
| Occupational therapist + 2 families | Stage 5 gate | REVIEW-QUEUE #12 |
| Groq DPA / VoxCPM2 / Qwen licences | First pilot traffic | REVIEW-QUEUE #13 · procedure: `docs/setup/02-groq-and-model-licences.md` |
