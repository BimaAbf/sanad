# سند · SANAD

Arabic-first (Egyptian colloquial) AI learning and developmental-tracking
platform for children with Down syndrome and their caregivers.

> **Deterministic core, AI at bounded decision points.** Every number a
> caregiver sees is computed by tested code. The LLM only interprets, ranks,
> narrates, and flags — never scores, never diagnoses, never invents an item.

Architecture lives in [`docs/`](docs/README.md). Build order is
[`docs/09`](docs/09-build-prompts.md); current state is [`PROGRESS.md`](PROGRESS.md);
**what needs a human is [`REVIEW-QUEUE.md`](REVIEW-QUEUE.md) — read that first.**

---

## 15-minute onboarding

### 0. Prerequisites

| Tool | Version | Install |
|---|---|---|
| Docker Desktop | any current | <https://docs.docker.com/desktop/> |
| Node | ≥ 22 | <https://nodejs.org> |
| pnpm | ≥ 11 | `npm i -g pnpm` |
| uv | ≥ 0.11 | <https://docs.astral.sh/uv/> |
| just | ≥ 1.5 | `npm i -g rust-just` |

Python is **not** a prerequisite: `uv` fetches the pinned 3.12 toolchain.

### 1. Bring it up

```
just bootstrap
just up
```

`bootstrap` copies `.env.example` → `.env`, installs both toolchains, syncs the
fonts, starts Postgres/Redis/MinIO/Mailhog, and migrates both databases.

`up` is the one command for everything after that. It runs a preflight that
names every missing prerequisite **and what that absence breaks**, brings up the
containers, migrates, starts the API on **:8000** and the web app on **:3000**,
and streams every log line from all of them into one colour-coded view — with
the API's structured JSON re-rendered as prose, one line per HTTP request
(`503 GET /voice/health 32.8ms req=0d20cb28`), and the same stream written raw
to `logs/dev-<timestamp>.log`. Ctrl-C stops the children and prints a request
summary. `just up --help` for the flags; `just dev` is still there if you want
the plain turbo runner.

**To run it the way it would run when deployed** — production settings, a real
RS256 keypair, no reloader, two uvicorn workers, Next serving a built app and
`/docs` correctly disabled:

```
just prod-env      # once: writes .env.production-local, never overwrites
just up-prod
```

That is the same process invocation the container images use, without needing a
Docker daemon to build them. What it can and cannot exercise today is in
[`docs/setup/04-running-it-deployed.md`](docs/setup/04-running-it-deployed.md).

| URL | What |
|---|---|
| <http://localhost:3000/home> | caregiver app |
| <http://localhost:3000/play> | child app |
| <http://localhost:3000/console> | clinician console |
| <http://localhost:8000/health> | liveness — no dependencies |
| <http://localhost:8000/health/ready> | readiness — db, redis, s3 individually |
| <http://localhost:8000/docs> | OpenAPI (disabled in production) |
| <http://localhost:59001> | MinIO console (`sanadminio` / `sanadminio-dev-secret`) |
| <http://localhost:58025> | Mailhog |

Host ports are offset into the 5xxxx range so this stack coexists with another
project's Postgres/Redis/MinIO on the same machine.

### 2. Check it

```
just test        # the CI gate, verbatim
just test-quick  # the same minus the five tests that need a live Postgres
just lint
just guards
```

**It runs without Docker, and says so.** If the daemon is not answering, `just
up` still starts the API — `/docs`, `/health` and every pure route work — and
prints exactly which routes will fail and why, rather than coming up quietly
broken. Five integration tests fail for the same reason; that is BLOCKED.md #1.

### 3. You do not need an API key

The architecture runs on fixtures and deterministic fallbacks by design.
Credentials are needed at four specific gates only — see [`SETUP.md`](SETUP.md) §2
for which, and [`docs/setup/`](docs/setup/README.md) for how to obtain each one.
If a key is absent the system runs in fixture mode and says so; it never stubs a
key with a fake value to make a test pass. `just up` prints the whole table on
startup: which are set, and for each absent one, the mode it runs in instead.

---

## Layout

```
apps/web/            Next.js 15 — three route groups: (app) (play) (console)
apps/web-e2e/        Playwright
services/api/        FastAPI · app/core, app/ai, app/guardrails, app/modules
packages/config/     shared eslint · tsconfig · tailwind preset · stylelint
packages/ui/         shared components + tokens
packages/api-client/ generated from openapi.json — do not hand-edit
tools/dev/          `just up` — preflight, process supervision, one log stream
tools/voice_render/ offline TTS render plan + `just voice-script`
tools/guards/       the five CI guards, each with a violation fixture
infra/               terraform + docker
tools/guards/        the four CI guard checks, and the fixtures proving they fire
tools/lint/          banned-terms lint, branch-coverage gate
evals/               golden datasets + runner
docs/                the architecture package
```

## The rules the tooling enforces for you

| Rule | Enforced by | Fails on |
|---|---|---|
| No physical CSS properties | stylelint | `margin-left: 4px` |
| No copy that frames a child as deficient | `tools/lint/banned_terms.py` | `متأخر`, "delay", "behind", "score" |
| Every child-scoped route is authorised | `tools/guards/route_authorisation.py` | a `{child_id}` route without `require_child_access` |
| One and only one model client | `tools/guards/single_anthropic_client.py` | `Anthropic()` outside `app/ai/gateway.py` |
| Prompt caching actually hits | `tools/guards/prompt_cache_hit.py` | `cache_read_input_tokens == 0` |
| Guardrail layers are declared | `tools/guards/required_guardrail_layer.py` | a decision point missing its layer |
| No PII in logs | `app/core/logging.py` allow-list | any field not on the list |
| 100% branch coverage on the core | `tools/lint/coverage_gate.py` | an untaken branch in `domain/` or `guardrails/` |

Each guard has a violation fixture and a control fixture in
`tools/guards/fixtures/`, and `tools/guards/test_guards.py` asserts it fires on
one and stays quiet on the other. A guard that silently matches nothing must not
be able to look like a passing guard.

## Contributing

- Conventional commits.
- `business rules → service.py` · `SQL → repository.py` · `pure logic → domain.py`
  (`domain.py` may import nothing from the project but other `domain.py` modules).
- Every error is RFC 9457 with a `message_ar` that is always safe to show a caregiver.
- Any decision a prompt left open gets a `docs/adr/NNN-*.md`.
- **Never author clinical content, Arabic curriculum labels, or caregiver copy.**
  Placeholders carry a `PLACEHOLDER — NOT FOR CLINICAL USE` header and an entry
  in `REVIEW-QUEUE.md`.
