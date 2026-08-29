/**
 * Copy the Arabic and Latin subsets of IBM Plex Sans Arabic out of the npm
 * package into public/fonts.
 *
 * Self-hosted (no request to a font CDN — docs/07 forbids third-party requests
 * from a page a child uses) and subset (arabic + latin only: cyrillic and greek
 * would triple the payload for glyphs this product never renders).
 *
 * The .woff2 files are build output, not source, so they are gitignored. This
 * runs from predev and prebuild, so a clean clone is never missing them.
 */
import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const source = join(here, "..", "node_modules", "@fontsource", "ibm-plex-sans-arabic", "files");
const target = join(here, "..", "public", "fonts");

/** [package file, public file] — weights 400 (body) and 600 (headings) only. */
const FILES = [
  ["ibm-plex-sans-arabic-arabic-400-normal.woff2", "ibm-plex-sans-arabic-400.woff2"],
  ["ibm-plex-sans-arabic-arabic-600-normal.woff2", "ibm-plex-sans-arabic-600.woff2"],
  ["ibm-plex-sans-arabic-latin-400-normal.woff2", "ibm-plex-sans-arabic-latin-400.woff2"],
  ["ibm-plex-sans-arabic-latin-600-normal.woff2", "ibm-plex-sans-arabic-latin-600.woff2"],
];

if (!existsSync(source)) {
  console.error(
    "@fontsource/ibm-plex-sans-arabic is not installed. Run `pnpm install` first.",
  );
  process.exit(1);
}

mkdirSync(target, { recursive: true });
for (const [from, to] of FILES) {
  copyFileSync(join(source, from), join(target, to));
}
console.warn(`synced ${FILES.length} font files to public/fonts`);
