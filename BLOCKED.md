# BLOCKED

Anything the orchestrator cannot proceed on, and what would unblock it.

_Last updated: 2026-08-29 · after P09–P15_

---

## 1. The Docker daemon stopped and did not recover

**This is the only hard blocker.**

`docker info` began hanging indefinitely partway through P01. It survived a full
Docker Desktop process kill, a `wsl --shutdown`, and a manual start of the
`docker-desktop` WSL distro (which did come back to `Running` — the daemon still
did not answer).

**Retried at the start of P09.** The symptom has changed and has not improved:
the command now returns immediately with

```
failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine:
The system cannot find the file specified.
```

Starting `Docker Desktop.exe` did not bring the named pipe back. So it is no
longer a hang, it is an absence — which rules out a wedged daemon and points at
the Desktop installation itself.

**What it blocks:**

| Blocked | Why |
|---|---|
| Migrations `0002`–`0004` | Never executed. Only `0001` has ever run against real Postgres. |
| `repository.py` in identity and children | Pure SQL, ~35% covered, cannot be exercised. |
| `tests/integration/test_stack.py` | 5 tests, correctly marked `integration`. |
| The `ai_cannot_grant` CHECK constraint | P07 requires proving via raw SQL that an AI verdict cannot promote a child to `mastered`. The application rule is tested; **the database backstop is not.** |
| P05's LangGraph checkpointer | Needs `AsyncPostgresSaver` against a live database. |
| Export and erasure completeness | P02 requires walking every foreign key to `children`. |
| Migrations `0005`–`0006` | Written in P10/P11. Events partitioning, the rollup upserts, the `dedupe_key` unique index and the `nudges_sent <= 3` CHECK have never run. |
| `progress/repository.py` | 0% covered. Every line is SQL. |
| The notification dedupe guarantee | docs/10 T11 §10 asks for proof that **Postgres** rejects a duplicate. What exists is an assertion about the DDL text. |
| Every Docker image | Neither Dockerfile has ever been built, so the Trivy gate in CI has never scanned anything. |

**What would unblock it:** a working Docker daemon. Then:

```
just migrate && just migrate-test && just test
```

I would not trust the DDL in `0002`–`0004` until that has run. They are
transcribed from `docs/02` and reviewed, but transcription errors in DDL are
exactly what a first migration run catches.

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
| Nour voice talent | **Now** — longest lead time in the project | REVIEW-QUEUE #10 |
| Speech-language therapist | Stage 5 voice gate | REVIEW-QUEUE #8, #9 |
| Occupational therapist + 2 families | Stage 5 gate | REVIEW-QUEUE #12 |
| Groq DPA / VoxCPM2 / Qwen licences | First pilot traffic | REVIEW-QUEUE #13 |
