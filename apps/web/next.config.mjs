import path from "node:path";

import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./src/i18n.ts");

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  eslint: { ignoreDuringBuilds: true },
  // `apps/web/Dockerfile` copies .next/standalone and runs `node
  // apps/web/server.js`. Without a standalone build Next never emits that
  // directory, the image build fails at the COPY, and the failure reads as a
  // broken Dockerfile rather than a missing config key. The image-size argument
  // in that file's comment -- ~180 MB traced instead of ~900 MB of workspace --
  // is what this buys.
  //
  // Behind an env var, not on unconditionally, because `next start` refuses to
  // serve a standalone build ("does not work with output: standalone"). The
  // Dockerfile's build stage sets NEXT_OUTPUT=standalone; a local
  // `pnpm --filter @sanad/web build && start` stays on the ordinary path.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  // A pnpm workspace hoists node_modules above apps/web, so the file tracer has
  // to start from the repo root or the standalone bundle ships without its
  // dependencies.
  outputFileTracingRoot: path.join(import.meta.dirname, "../../"),
};

export default withNextIntl(nextConfig);
