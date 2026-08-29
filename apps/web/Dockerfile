# syntax=docker/dockerfile:1.7
#
# Production image for the Next.js app. docs/08 §3.
#
# Note on where this actually runs: docs/12 §Δ3 moves the static tier to
# Cloudflare Pages, so in the default deployment this image serves only the SSR
# and RSC routes — the caregiver dashboard and the assessment runner. The child
# app's assets come from R2 and never touch it. The image is still built and
# scanned, because the AWS path in docs/08 §2 remains the documented scale-up
# and it needs a container.

FROM node:22-slim AS base
ENV PNPM_HOME=/pnpm PATH="/pnpm:$PATH" NEXT_TELEMETRY_DISABLED=1
RUN corepack enable

# --- dependencies ----------------------------------------------------------
FROM base AS deps
WORKDIR /repo
COPY pnpm-lock.yaml pnpm-workspace.yaml package.json ./
COPY packages/config/package.json packages/config/
COPY apps/web/package.json apps/web/
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile

# --- build -----------------------------------------------------------------
FROM deps AS build
WORKDIR /repo
COPY . .
# `standalone` output: the runtime layer then carries the traced node_modules
# subset rather than the whole workspace, which is the difference between a
# ~180 MB image and a ~900 MB one.
#
# next.config.mjs reads this rather than hard-coding `output: "standalone"`,
# because `next start` refuses to serve a standalone build and that would break
# every local production run. Removing this line does not fail the build -- it
# fails the COPY below, which is a much less obvious symptom.
ENV NEXT_OUTPUT=standalone
RUN pnpm --filter @sanad/web build

# --- runtime ---------------------------------------------------------------
FROM node:22-slim AS runtime
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin appuser

COPY --from=build --chown=appuser:appuser /repo/apps/web/.next/standalone ./
COPY --from=build --chown=appuser:appuser /repo/apps/web/.next/static ./apps/web/.next/static
COPY --from=build --chown=appuser:appuser /repo/apps/web/public ./apps/web/public

USER appuser
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:3000/ || exit 1

CMD ["node", "apps/web/server.js"]
