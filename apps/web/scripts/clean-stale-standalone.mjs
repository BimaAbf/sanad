/**
 * Remove a leftover .next/standalone before building.
 *
 * `output: "standalone"` is only ever wanted inside the Docker build, where the
 * build stage sets NEXT_OUTPUT=standalone (see next.config.mjs and
 * apps/web/Dockerfile). A container starts from a clean tree, so it never meets
 * this problem — but a local checkout that has produced a standalone build once
 * keeps the directory, and the NEXT build fails:
 *
 *   [Error: EPERM: operation not permitted, scandir
 *    '...\.next\standalone\apps\web\node_modules\react']
 *
 * The standalone bundle contains pnpm's symlinked node_modules. With
 * `outputFileTracingRoot` pointing at the repo root, the file tracer walks into
 * it, and on Windows `scandir` through those symlinks needs privileges that a
 * normal shell does not have. The build dies with an error that names `react`
 * and looks like a dependency problem, which is about as misleading as it gets.
 *
 * So: delete it first. It is build output, it is gitignored, and it is
 * regenerated in one command whenever it is actually wanted.
 *
 * Runs from prebuild, alongside sync-fonts.
 */
import { existsSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const standalone = join(here, "..", ".next", "standalone");

// Keep it when this build is the one producing it — the Dockerfile sets the
// variable, and deleting the previous output there would be harmless but
// pointless work in an image layer.
if (process.env.NEXT_OUTPUT === "standalone") {
  process.exit(0);
}

if (existsSync(standalone)) {
  rmSync(standalone, { recursive: true, force: true });
  console.warn("removed stale .next/standalone (see scripts/clean-stale-standalone.mjs)");
}
