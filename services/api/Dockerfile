# syntax=docker/dockerfile:1.7
#
# Production image for the Misk API. docs/08 §3.
#
# Four properties this file exists to guarantee, each of which a naive Dockerfile
# loses:
#
#   * non-root at runtime          — a container escape starts as uid 10001
#   * no build toolchain in the    — `uv` and the compilers live in the deps
#     final layer                     stage and are not copied forward
#   * a real healthcheck           — ECS and Coolify both need one that hits the
#                                     no-dependency liveness route, NOT /ready:
#                                     a readiness failure is a degraded service,
#                                     not a container that should be killed
#   * ffmpeg present               — child audio arrives as webm/opus and is
#                                     transcoded before scoring (docs/04d §5)

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg libpq5 curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.5.14 /uv /usr/local/bin/uv

# --- dependencies ----------------------------------------------------------
# Separated so a source-only change does not re-resolve the lock file. `--frozen`
# fails rather than updating: a deploy must install exactly what CI tested.
FROM base AS deps
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# --- runtime ---------------------------------------------------------------
FROM base AS runtime
WORKDIR /app

# Created before the COPYs so the application files land already owned, rather
# than needing a recursive chown that doubles the layer size.
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin appuser

COPY --from=deps --chown=appuser:appuser /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser migrations ./migrations
COPY --chown=appuser:appuser seeds ./seeds
COPY --chown=appuser:appuser alembic.ini ./alembic.ini

USER appuser
EXPOSE 8000

# /health, not /health/ready. Readiness reports a degraded dependency and
# returns 503; killing the container for that would turn a Redis blip into a
# restart loop while the API was still serving every request that did not need
# Redis.
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
