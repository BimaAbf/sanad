/**
 * The Tailwind preset and globals.css both restate the token values from
 * docs/06-frontend-ux.md §2. Two copies of a colour ramp drift. This asserts
 * they do not, by parsing the design document.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import preset from "@sanad/config/tailwind";

const REPO_ROOT = join(import.meta.dirname, "..", "..", "..");
const DOCS = join(REPO_ROOT, "docs", "06-frontend-ux.md");
const GLOBALS = join(import.meta.dirname, "styles", "globals.css");

function tokensFromDocs(): Map<string, string> {
  const text = readFileSync(DOCS, "utf8");
  const section = text.split("## 2. Design tokens")[1]!.split("## 3.")[0]!;
  const tokens = new Map<string, string>();
  for (const match of section.matchAll(/(--[a-z0-9-]+):\s*([^;]+);/g)) {
    tokens.set(match[1]!, match[2]!.trim());
  }
  return tokens;
}

describe("design tokens", () => {
  const documented = tokensFromDocs();

  it("parses the documented token set", () => {
    expect(documented.size).toBeGreaterThan(40);
  });

  it("globals.css declares every documented token", () => {
    const css = readFileSync(GLOBALS, "utf8");
    const missing = [...documented.keys()].filter((name) => !css.includes(`${name}:`));
    expect(missing).toEqual([]);
  });

  it("globals.css uses the documented colour values", () => {
    const css = readFileSync(GLOBALS, "utf8").toLowerCase();
    for (const [name, value] of documented) {
      if (!value.startsWith("#")) continue;
      expect(css, `${name} should be ${value}`).toContain(`${name}: ${value.toLowerCase()}`);
    }
  });

  it("the tailwind preset uses the documented brand colours", () => {
    const colors = preset.theme!.extend!.colors as Record<string, never>;
    const expected: Array<[string, string]> = [
      ["--c-primary", (colors.primary as unknown as { DEFAULT: string }).DEFAULT],
      ["--c-accent", (colors.accent as unknown as { DEFAULT: string }).DEFAULT],
      ["--c-ink", (colors.ink as unknown as { DEFAULT: string }).DEFAULT],
      ["--c-growing", colors.growing as unknown as string],
      ["--c-practising", colors.practising as unknown as string],
      ["--c-resting", colors.resting as unknown as string],
      ["--c-attention", colors.attention as unknown as string],
    ];
    for (const [token, actual] of expected) {
      expect(actual.toLowerCase(), token).toBe(documented.get(token)!.toLowerCase());
    }
  });

  it("body text is 17px at 1.9 line height", () => {
    expect(documented.get("--t-base")).toBe("17px");
    expect(documented.get("--lh-base")).toBe("1.9");
    const css = readFileSync(GLOBALS, "utf8");
    expect(css).toContain("font-size: var(--t-base)");
    expect(css).toContain("line-height: var(--lh-base)");
  });

  it("child touch targets exceed the 80px requirement", () => {
    expect(Number.parseInt(documented.get("--touch-child")!, 10)).toBeGreaterThanOrEqual(80);
  });
});
