# ADR 001 — Stack and scaffold decisions

- **Status:** accepted
- **Date:** 2026-08-29
- **Component:** P00 — repository scaffold & shared foundations
- **Supersedes:** nothing
- **Context docs:** `docs/08-infrastructure.md` §1, §3, §4 · `docs/06-frontend-ux.md` §2 · `docs/02-data-model.md` §2

## Context

P00 specifies the stack but leaves a number of choices open. This records them,
plus the two places the environment forced a deviation from the written design.

## Decisions

### D1 — Host ports offset into the 5xxxx range

`docs/08` implies the conventional ports. This machine already runs another
project's Postgres (5432), Redis (6379), MinIO (9000/9001) and Mailhog
(1025/8025). Rather than ask a developer to stop unrelated work to run this one,
`docker-compose.yml` publishes on 55432 / 56379 / 59000 / 59001 / 51025 / 58025.
Container-internal ports are unchanged, so nothing in `infra/` or the Dockerfile
is affected.

*Consequence:* `.env.example` carries the offset ports. A developer copying a
connection string out of a doc that predates this ADR will connect to the wrong
database. The README states the ports explicitly for that reason.

### D2 — Configuration is read from an absolute repo-root `.env`

`pydantic-settings` resolves `env_file` relative to the working directory, and
this project runs Python from at least three of them (`uv run` at
`services/api`, `alembic` at `services/api`, `pytest` at the repo root in CI).
`app/core/config.py` therefore resolves `ENV_FILES` from `__file__`: repo-root
`.env` first, then an optional `services/api/.env` override.

### D3 — No default for any credential

Every datastore field is `Field(...)`. A missing variable raises
`ConfigurationError` naming every offending variable with its `MISK_` prefix. A
default that "works locally" is how a staging deployment ends up silently
pointing at the wrong bucket.

### D4 — `/health` has no dependencies; `/health/ready` has all of them

`/health` returns 200 while the process is alive, so an orchestrator never kills
an instance because Redis blinked. `/health/ready` probes db, redis and s3
individually and returns 503 if any is down. Probes never raise — a dead
dependency is a 503, not a 500. *Verified:* stopping Redis produced
`503 {"redis": {"status": "error"}}` while `/health` stayed 200.

### D5 — The log field allow-list is a deny-by-default filter, plus a substring ban

`app/core/logging.py` drops every key not on `ALLOWED_FIELDS` and records what it
dropped. On top of that, any key containing `password`, `token`, `phone`,
`name`, `audio` … is dropped *even if it is on the allow-list*, so a careless
addition to the list cannot open a hole.

*Open tension found while building:* the metering fields `input_tokens`,
`output_tokens` and `cache_read_input_tokens` are integers the cost model needs,
but they contain the substring `token`. Rather than weaken the substring rule,
they are listed in an explicit `EXEMPT_FIELDS` set, and a test asserts every
member of that set ends in `tokens`. Adding to it is a deliberate, visible act.

### D6 — 422 is written as a literal, not `status.HTTP_422_*`

Starlette 1.6 deprecated `HTTP_422_UNPROCESSABLE_ENTITY` in favour of
`HTTP_422_UNPROCESSABLE_CONTENT`. Using the literal avoids a deprecation warning
now and a rename later.

### D7 — Fonts come from npm, not a download script

P00 asks for IBM Plex Sans Arabic "self-hosted and subset".
`@fontsource/ibm-plex-sans-arabic` already ships per-script subsets, so
`apps/web/scripts/sync-fonts.mjs` copies the arabic and latin `.woff2` files into
`public/fonts` from `predev`/`prebuild`. The files are build output and are
gitignored; the lockfile pins the version. This avoids an unpinned network fetch
in the build and keeps the OFL licence traceable through the dependency tree.

*Verified:* all four faces report `loaded`, and cumulative layout shift is 0.

### D8 — The four guard checks are implemented now, not stubbed

P00 permits stubs. Two of the four (`single-anthropic-client`,
`route-authorisation`) are cheap to write correctly and expensive to
retrofit — by the time P03 exists, a violation may already be in the tree. All
four are fully implemented; two currently report **SKIP** because the code they
inspect does not exist yet, and each says which P-prompt activates it.

The important part is `tools/guards/test_guards.py`: every guard is run against
a violation fixture (must fail) and a control fixture (must pass). A guard that
silently matches nothing is otherwise indistinguishable from a passing one, and
that is the failure mode these checks exist to prevent.

### D9 — A separate `misk_test` database

`tests/conftest.py` points at `misk_test`, created by
`infra/docker/postgres-init/`. `just test` can never truncate the data a
developer is looking at in `just dev`.

### D10 — Arabic strings in `apps/web/src/messages/ar-EG.json` are placeholders

They carry a `PLACEHOLDER — NOT FOR CLINICAL USE` header in `_meta` and an entry
in `REVIEW-QUEUE.md`. They exist so the shell renders and the banned-terms lint
has something to lint. **No caregiver- or child-facing copy in this repository
has been written or reviewed by a native Egyptian Arabic speaker.**

## Consequences

- Every acceptance criterion in P00 is met and was verified by running it, with
  one qualification: `just bootstrap && just dev` was verified as its constituent
  commands on an already-initialised checkout, not from a genuinely clean clone
  (there is no remote yet). See `PROGRESS.md`.
- The `contract`, `e2e`, `perf` and `evals` CI jobs are placeholders that echo
  which P-prompt activates them. They are visible in the job list rather than
  absent, so nobody concludes the coverage exists.
