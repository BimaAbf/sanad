# PROGRESS

One row per component. **Status** is one of `not started` · `in progress` ·
`DONE` · `DONE, gate open` · `BLOCKED`. A component is never `DONE` on a
sub-session's report — only after the orchestrator re-ran the gate command
itself and read the real output.

_Last updated: 2026-08-29_

| # | Component | Status | Branch | Tests | Coverage | Gates open |
|---|---|---|---|---|---|---|
| P00 | Repository scaffold | **DONE** | `feat/p00-scaffold` | 40 | 96% line | — |
| P01 | C01 Identity & access | **DONE** (service layer) | `feat/p00-scaffold` | 87 | 98% service · 99% router | repository.py needs a DB |
| P02 | C02 Child profile & consent | **DONE** (service layer) | `feat/p00-scaffold` | 33 | 100% service · 100% gate | repository.py needs a DB |
| P03 | C15 Gateway + guardrails | **DONE, gate open** | `feat/p00-scaffold` | 121 | **100% branch** | red-team corpus (#7) |
| P04 | C03 Assessment engine | **DONE, gate open** | `feat/p00-scaffold` | 81 | **100% branch on domain/** | clinician verification (#4) |
| P05 | C04 PGEE AI orchestrator | **partial** | `feat/p00-scaffold` | — | — | graph/SSE not built — see below |
| P06 | C05 Content & curriculum | **DONE, gate open** | `feat/p00-scaffold` | 49 | **100% branch** | native-speaker sign-off (#6) |
| P07 | C06 Adaptive engine (BKT) | **DONE, gate open** | `feat/p00-scaffold` | 72 | **100% branch on domain/** | BKT parameters + the addition (#5) |
| P08 | C07 Tutor orchestrator | **DONE** | `feat/p00-scaffold` | 67 | **100% branch** | — |
| P09 | C08 Voice gateway | not started | — | — | — | SLT corpus; native speaker on audio |
| P10 | C09 Progress | not started | — | — | — | — |
| P11 | C10 Notifications | not started | — | — | — | — |
| P12 | C12 Caregiver app | not started | — | — | — | — |
| P13 | C13 Child app | not started | — | — | — | OT accessibility; real-device audio |
| P14 | C14 Clinician console | not started | — | — | — | — |
| P15 | Infrastructure & CI | not started | — | — | — | — |

**589 unit tests, all passing.** 100% branch coverage on every `domain/`
package, `app/guardrails/`, `app/ai/` and `app/modules/tutor_ai/`.

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
| 1 — Spine | P00, P01, P02, P15 | P00/P01/P02 built; **P15 not started**; DB-backed tests blocked |
| 2 — Assessment, no AI | P04 | Built, 100% branch. **Gate needs a clinician (#4).** |
| 3 — Learning, no AI | P06, P07 | Built. Random-tapper test green at 1000 sims. **Gates #5, #6.** |
| 4 — AI layer | P03, P05, P08 | P03/P08 built; **P05 graph + SSE outstanding**. Gate #7. |
| 5 — Voice, clients, ops | P09–P14 | not started |

**No stage gate has been crossed.** Stages 2 and 3 were required to produce a
working product with zero AI code written; that ordering was followed — P04, P06
and P07 were built and fully tested before P03 was started.

---

## P00 — Repository scaffold & shared foundations · DONE

**Branch:** `feat/p00-scaffold` · **ADR:** [`docs/adr/001-stack.md`](docs/adr/001-stack.md)

### Acceptance criteria, verified

| Criterion | Result | Command / evidence |
|---|---|---|
| `just bootstrap && just dev` brings up api :8000 and web :3000 | **PASS** (with one caveat) | `just dev` verified end to end: turbo runs `@misk/api:dev` and `@misk/web:dev` together; `:8000/health` 200, `:8000/health/ready` 200, and `/home`, `/play`, `/console` all 200. **Caveat:** not run from a genuinely clean clone — there is no git remote yet. |
| `GET /health` returns 200 with no database dependency | **PASS** | With Redis stopped: `{"status":"ok","version":"0.1.0"}` HTTP 200 |
| `GET /health/ready` reports db, redis and s3 individually | **PASS** | Healthy: `{"status":"ok","checks":{"db":{"status":"ok"},"redis":{"status":"ok"},"s3":{"status":"ok"}}}` 200. Redis stopped: `{"status":"degraded","checks":{"redis":{"status":"error","reason":"TimeoutError"}}}` 503 |
| Unhandled exception → valid RFC 9457 with `message_ar`, never a stack trace | **PASS** | `tests/unit/test_health_and_errors.py::test_unhandled_exception_is_problem_details` asserts 500, `application/problem+json`, `message_ar` present, and that neither `ValueError`, the exception text, nor `Traceback` appears in the body |
| `just lint` passes: ruff, mypy --strict, eslint, stylelint | **PASS** | `ruff check` All checks passed · `ruff format --check` 25 files already formatted · `mypy --strict app` Success: no issues found in 16 source files · `tsc --noEmit` exit 0 · `stylelint` exit 0 |
| stylelint demonstrably fails on `margin-left: 4px` | **PASS** | `tools/guards/fixtures/physical-properties.css.fixture` → exit 2, 6 errors, each naming the logical replacement. Control fixture → exit 0. Asserted by `tools/guards/test_guards.py::test_stylelint_bans_physical_properties` |
| A missing required env var causes a clear startup failure naming the variable | **PASS** | Observed for real when alembic ran from the wrong directory: `ConfigurationError: Misk API cannot start … MISK_DATABASE_URL: Field required …`. Asserted by `test_config.py::test_missing_required_variable_names_it` |
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
