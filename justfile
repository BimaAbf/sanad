# مِسك (Misk) — task runner.  `just --list` for everything.
#
# Recipes avoid `cd X && Y`: Windows PowerShell 5.1 has no `&&`. Python tasks use
# `uv --directory`, node tasks use `pnpm --filter`, so every line is a single
# command that runs identically on Windows, macOS and Linux.

api := "services/api"
web := "@misk/web"

default:
    @just --list

# One-time (idempotent) setup from a clean clone.
bootstrap: _env
    pnpm install
    pnpm --filter {{web}} sync-fonts
    uv --directory {{api}} sync --all-extras
    docker compose up -d --wait
    @just migrate
    @just migrate-test
    @echo "bootstrap complete -- run 'just dev'"

_env:
    @python tools/bootstrap_env.py

# Run api (:8000) and web (:3000).
dev:
    docker compose up -d
    pnpm exec turbo run dev --parallel

dev-api:
    uv --directory {{api}} run uvicorn app.main:app --reload --port 8000

dev-web:
    pnpm --filter {{web}} dev

test:
    uv --directory {{api}} run pytest -m "not live_ai" --cov --cov-report=term --cov-report=xml
    uv --directory {{api}} run python ../../tools/lint/coverage_gate.py
    pnpm exec turbo run test --filter=!@misk/api

lint:
    uv --directory {{api}} run ruff check .
    uv --directory {{api}} run ruff format --check .
    uv --directory {{api}} run mypy --strict app
    pnpm exec turbo run lint --filter=!@misk/api
    pnpm exec turbo run typecheck --filter=!@misk/api
    pnpm run stylelint
    python tools/lint/banned_terms.py

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

# Copy the subset IBM Plex Sans Arabic files out of npm into public/fonts.
fonts:
    pnpm --filter {{web}} sync-fonts

# The four CI guard checks, plus the test proving each fires on a violation.
guards:
    uv --directory {{api}} run pytest ../../tools/guards/test_guards.py
    uv --directory {{api}} run python ../../tools/guards/route_authorisation.py
    uv --directory {{api}} run python ../../tools/guards/single_anthropic_client.py
    uv --directory {{api}} run python ../../tools/guards/prompt_cache_hit.py
    uv --directory {{api}} run python ../../tools/guards/required_guardrail_layer.py

down:
    docker compose down

clean:
    docker compose down -v
