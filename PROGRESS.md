# PROGRESS

One row per component. **Status** is one of `not started` · `in progress` ·
`DONE` · `DONE, gate open` · `BLOCKED`. A component is never `DONE` on a
sub-session's report — only after the orchestrator re-ran the gate command
itself and read the real output.

_Last updated: 2026-08-29_

| # | Component | Status | Branch | Tests | Coverage | Gates open |
|---|---|---|---|---|---|---|
| P00 | Repository scaffold | **DONE** | `feat/p00-scaffold` | 40 (24 api · 10 guards · 6 web) | 96% line · 36/42 branch | — |
| P01 | C01 Identity & access | not started | — | — | — | — |
| P02 | C02 Child profile & consent | not started | — | — | — | — |
| P03 | C15 Gateway + guardrails | not started | — | — | — | red-team corpus (independent author) |
| P04 | C03 Assessment engine | not started | — | — | — | clinician verification of golden cases |
| P05 | C04 PGEE AI orchestrator | not started | — | — | — | — |
| P06 | C05 Content & curriculum | not started | — | — | — | native-speaker sign-off on 88 skills |
| P07 | C06 Adaptive engine (BKT) | not started | — | — | — | BKT parameter review |
| P08 | C07 Tutor orchestrator | not started | — | — | — | — |
| P09 | C08 Voice gateway | not started | — | — | — | SLT on scoring corpus; native speaker on audio |
| P10 | C09 Progress | not started | — | — | — | — |
| P11 | C10 Notifications | not started | — | — | — | — |
| P12 | C12 Caregiver app | not started | — | — | — | — |
| P13 | C13 Child app | not started | — | — | — | OT accessibility review; real-device audio |
| P14 | C14 Clinician console | not started | — | — | — | — |
| P15 | Infrastructure & CI | not started | — | — | — | — |

## Stage gates

| Stage | Components | State |
|---|---|---|
| 1 — Spine | P00, P01, P02, P15 | **P00 done; P01, P02, P15 outstanding** |
| 2 — Assessment, no AI | P04 | not started |
| 3 — Learning, no AI | P06, P07 | not started |
| 4 — AI layer | P03, P05, P08 | not started |
| 5 — Voice, clients, ops | P09–P14 | not started |

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
