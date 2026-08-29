# سند (Sanad) — task runner.  `just --list` for everything.
#
# Recipes avoid `cd X && Y`: Windows PowerShell 5.1 has no `&&`. Python tasks use
# `uv --directory`, node tasks use `pnpm --filter`, so every line is a single
# command that runs identically on Windows, macOS and Linux.
#
# Repo-level scripts run through `uv run --no-project --python 3.12` rather than
# a bare `python`, so the README's claim that Python is not a prerequisite is
# actually true: uv fetches the interpreter. `--no-project` keeps them out of
# the API's virtualenv -- they are stdlib-only on purpose.

# just runs recipes through `sh` by default, and Windows has no `sh` unless Git
# Bash's bin/ happens to be on PATH -- which it is not by default, so
# `just bootstrap` failed with "could not find the shell `sh`". PowerShell 5.1
# ships with every Windows 11 install, so it is the one shell that is always
# there. Verified for the three properties a task runner actually needs:
#
#   * a native command exiting non-zero fails the recipe;
#   * the remaining lines of that recipe do NOT run (so a pytest failure cannot
#     be followed by a coverage gate reporting green);
#   * a command that writes to stderr and exits 0 is NOT treated as a failure --
#     `uv` and `pnpm` both write progress there.
#
# `-NoProfile` so a recipe behaves the same for everyone regardless of what is
# in their profile. macOS and Linux keep the default `sh`.
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

api := "services/api"
web := "@sanad/web"

default:
    @just --list

# One-time (idempotent) setup from a clean clone.
bootstrap: _env
    pnpm install
    pnpm --filter {{web}} sync-fonts
    uv --directory {{api}} sync --all-extras
    docker compose up -d --wait
    docker compose run --rm minio-init
    @just migrate
    @just migrate-test
    @echo "bootstrap complete -- run 'just up'"

_env:
    @uv run --no-project --python 3.12 tools/bootstrap_env.py

# Run api (:8000) and web (:3000).
dev:
    docker compose up -d
    pnpm exec turbo run dev --parallel

# Preflight, containers, migrations, api and web; every log line from all of
# them in one colour-coded stream, also written to logs/dev-<timestamp>.log.
# THE one command -- everything running, everything observable. `just up --help`.
up *ARGS:
    uv run --no-project --python 3.12 tools/dev/run.py {{ARGS}}

# Production settings, a fresh RS256 keypair and real secrets, because
# SANAD_ENVIRONMENT=production refuses the local-dev ones. Never overwrites.
# Write .env.production-local -- one-time setup for `just up-prod`.
prod-env *ARGS:
    uv --directory {{api}} run python ../../tools/dev/make_prod_env.py {{ARGS}}

# The same processes the container images run -- production settings, no
# reloader, two uvicorn workers, Next serving a real build. Needs `just prod-env`
# once, and rebuilds the web app each time.
# Run the stack in its deployed shape, on this machine.
up-prod:
    pnpm --filter {{web}} build
    uv run --no-project --python 3.12 tools/dev/run.py --prod

dev-api:
    uv --directory {{api}} run uvicorn app.main:app --reload --port 8000

dev-web:
    pnpm --filter {{web}} dev

# Five integration tests need a real Postgres and Redis, and a `test` that quietly
# skipped them would report green on an untested stack -- so this fails without
# Docker, correctly. `just test-quick` is the one to use while it is down.
# The CI gate, verbatim: pytest, then the branch-coverage gate, then the web tests.
test:
    uv --directory {{api}} run pytest -m "not live_ai" --cov --cov-report=term --cov-report=xml
    uv --directory {{api}} run python ../../tools/lint/coverage_gate.py
    uv --directory {{api}} run pytest ../../tools/dev/test_dev_runner.py ../../tools/voice_render/test_recording_script.py --no-cov
    pnpm exec turbo run test --filter=!@sanad/api

# NOT the CI gate -- use it while BLOCKED.md #1 is open, so the coverage gate, the
# tooling tests and the web tests still get run on a machine with no Docker.
# Everything `test` runs, except the five tests that need a live stack.
test-quick:
    uv --directory {{api}} run pytest -m "not live_ai and not integration" --cov --cov-report=term --cov-report=xml
    uv --directory {{api}} run python ../../tools/lint/coverage_gate.py
    uv --directory {{api}} run pytest ../../tools/dev/test_dev_runner.py ../../tools/voice_render/test_recording_script.py --no-cov
    pnpm exec turbo run test --filter=!@sanad/api

lint:
    uv --directory {{api}} run ruff check .
    uv --directory {{api}} run ruff format --check .
    uv --directory {{api}} run mypy --strict app
    pnpm exec turbo run lint --filter=!@sanad/api
    pnpm exec turbo run typecheck --filter=!@sanad/api
    pnpm run stylelint
    uv run --no-project --python 3.12 tools/lint/banned_terms.py

fmt:
    uv --directory {{api}} run ruff check --fix .
    uv --directory {{api}} run ruff format .
    pnpm exec prettier --write "apps/**/*.{ts,tsx,css,json}" "packages/**/*.{ts,tsx,css,json}"

migrate:
    uv --directory {{api}} run alembic upgrade head

# Migrate the separate test database (`just test` never touches dev data).
migrate-test:
    uv --directory {{api}} run --env-file ../../.env.test alembic upgrade head

migration name:
    uv --directory {{api}} run alembic revision --autogenerate -m "{{name}}"

seed:
    uv --directory {{api}} run python -m app.cli seed

eval:
    uv --directory {{api}} run python -m app.cli eval

# Run one scheduled job by name -- the entrypoint a platform cron invokes.
# `tools/dev` does NOT run these on a timer: the cadences in
# app/workers/schedule.py are Cairo local times, and a resident scheduler
# started in January is an hour wrong from April.
#
#   just worker bkt_decay        forgetting for skills past their review date
#   just worker rollup_rebuild   the nightly rollup backstop, plus partitions
#
# Seven of the nine declared jobs have no body yet. Asking for one names what
# it is waiting for and exits 1, rather than reporting a run that did nothing.
worker job:
    uv --directory {{api}} run python -m app.cli worker {{job}}

# Inspect the LangChain/RAG path against the real database, stage by stage:
# the built corpus, the pgvector retrieval with scores, the red-flag screen,
# exactly what went to the provider after redaction, and whether the answer
# came from the model or the deterministic fallback.
#
#   just rag demo                     seed a child with real history
#   just rag "all --child <uuid>"     index, then one of each
#   just rag "ask --child <uuid> --message '...'"
#
# With AI_LIVE=0 (the default) nothing reaches the network and every decision
# point reports `no_fixture` -- that is the baseline worth running first,
# because it tells you whether retrieval and the DB half work on their own.
rag args="demo":
    uv --directory {{api}} run python -m app.cli rag {{args}}

# Assembled from seeds/curriculum.py, so it carries a DO-NOT-RECORD banner until
# that file's REVIEWED_BY header is filled in. See docs/setup/01-nour-voice.md.
# Write dist/nour-recording-script.md -- the document you hand the voice talent.
voice-script:
    uv --directory {{api}} run python ../../tools/voice_render/build_recording_script.py

# Copy the subset IBM Plex Sans Arabic files out of npm into public/fonts.
fonts:
    pnpm --filter {{web}} sync-fonts

# Keep this list identical to `.github/workflows/ci.yml` job `guards`: a local
# `just guards` that runs fewer checks than CI is worse than no local recipe,
# because it reports green on a tree CI will reject.
# The five CI guard checks, plus the test proving each fires on a violation.
guards:
    uv --directory {{api}} run pytest ../../tools/guards/test_guards.py
    uv --directory {{api}} run python ../../tools/guards/route_authorisation.py
    uv --directory {{api}} run python ../../tools/guards/single_anthropic_client.py
    uv --directory {{api}} run python ../../tools/guards/prompt_cache_hit.py
    uv --directory {{api}} run python ../../tools/guards/required_guardrail_layer.py
    uv --directory {{api}} run python ../../tools/guards/destructive_migration.py

down:
    docker compose down

clean:
    docker compose down -v
