/**
 * T12 §6 / T13 §16 — contrast, measured rather than asserted.
 *
 * globals.css claims "every foreground/background pair meets >= 7:1 (WCAG
 * AAA)". This is the test that makes the comment true, and it reads the shipped
 * stylesheet rather than a copy of the values.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import {
  CAREGIVER_MIN_RATIO,
  CHILD_MIN_RATIO,
  GRAPHIC_MIN_RATIO,
  RENDERED_PAIRS,
  contrastRatio,
  failingPairs,
  meetsCaregiver,
  meetsChild,
  parseHex,
  relativeLuminance,
  tokensFrom,
} from "./contrast";

const CSS = readFileSync(join(import.meta.dirname, "..", "styles", "globals.css"), "utf8");
const TOKENS = tokensFrom(CSS);

describe("the maths", () => {
  it("matches the WCAG reference values", () => {
    expect(contrastRatio("#000000", "#ffffff")).toBeCloseTo(21, 5);
    expect(contrastRatio("#ffffff", "#ffffff")).toBeCloseTo(1, 5);
    // The canonical "web-safe" grey: #767676 on white is exactly at 4.5:1.
    expect(contrastRatio("#767676", "#ffffff")).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio("#777777", "#ffffff")).toBeLessThan(4.5);
  });

  it("is symmetric", () => {
    expect(contrastRatio("#1f6f5c", "#ffffff")).toBeCloseTo(contrastRatio("#ffffff", "#1f6f5c"), 9);
  });

  it("parses three- and six-digit hex", () => {
    expect(parseHex("#fff")).toEqual({ r: 255, g: 255, b: 255 });
    expect(parseHex("1F6F5C")).toEqual({ r: 31, g: 111, b: 92 });
    expect(() => parseHex("#zzz")).toThrow();
  });

  it("computes relative luminance at the endpoints", () => {
    expect(relativeLuminance({ r: 0, g: 0, b: 0 })).toBe(0);
    expect(relativeLuminance({ r: 255, g: 255, b: 255 })).toBeCloseTo(1, 9);
  });
});

describe("the shipped tokens", () => {
  it("parses out of globals.css", () => {
    expect(TOKENS.size).toBeGreaterThan(20);
    expect(TOKENS.get("--c-primary")).toBe("#1f6f5c");
  });

  it("every rendered pair meets its audience's minimum", () => {
    expect(failingPairs(TOKENS)).toEqual([]);
  });

  it("checks all three audiences, so the list is not accidentally caregiver-only", () => {
    const audiences = new Set(RENDERED_PAIRS.map((pair) => pair.audience));
    expect([...audiences].sort()).toEqual(["caregiver", "child", "graphic"]);
  });

  it("the child app's text clears 7:1, not merely 4.5:1", () => {
    const ink = TOKENS.get("--c-ink")!;
    const white = TOKENS.get("--k-white")!;
    expect(contrastRatio(ink, white)).toBeGreaterThanOrEqual(CHILD_MIN_RATIO);
    expect(meetsChild(ink, white)).toBe(true);
  });

  it("the primary button label clears the caregiver minimum", () => {
    expect(meetsCaregiver(TOKENS.get("--c-surface")!, TOKENS.get("--c-primary")!)).toBe(true);
  });

  it("the semantic colours avoid red and green as pass/fail signals", () => {
    // Not a contrast property, but it lives with the palette: red reads as
    // failure and this product has no failure states (docs/06 §2).
    expect(CSS.toLowerCase()).toContain("deliberately not red/green");
    expect(TOKENS.get("--c-growing")).not.toBe("#00ff00");
    expect(TOKENS.get("--c-attention")).not.toMatch(/^#(f|e|d)[0-9a-f]0{4}$/);
  });

  it("the two low-contrast semantic colours are swatch-only, and say so", () => {
    // A FINDING, kept as a regression test. globals.css claimed every pair met
    // 7:1. Measured: --c-practising is 3.26:1 and --c-resting is 3.58:1 on
    // white. Both are fine as a skill-map fill (>= 3:1, SC 1.4.11) and neither
    // is usable as text, so there are now separate text tokens.
    const practising = TOKENS.get("--c-practising")!;
    const resting = TOKENS.get("--c-resting")!;
    const white = TOKENS.get("--c-surface")!;
    expect(contrastRatio(practising, white)).toBeLessThan(CAREGIVER_MIN_RATIO);
    expect(contrastRatio(practising, white)).toBeGreaterThanOrEqual(GRAPHIC_MIN_RATIO);
    expect(contrastRatio(resting, white)).toBeLessThan(CAREGIVER_MIN_RATIO);
    expect(contrastRatio(resting, white)).toBeGreaterThanOrEqual(GRAPHIC_MIN_RATIO);

    expect(contrastRatio(TOKENS.get("--c-practising-text")!, white)).toBeGreaterThanOrEqual(
      CAREGIVER_MIN_RATIO,
    );
    expect(contrastRatio(TOKENS.get("--c-resting-text")!, white)).toBeGreaterThanOrEqual(
      CAREGIVER_MIN_RATIO,
    );
  });
});

describe("the guard can fail", () => {
  it("reports a pair that does not meet its minimum", () => {
    const broken = new Map(TOKENS);
    broken.set("--c-ink", "#999999");
    const failures = failingPairs(broken);
    expect(failures.length).toBeGreaterThan(0);
    expect(failures.join(" ")).toContain("body text");
  });

  it("reports a missing token rather than silently passing", () => {
    const broken = new Map(TOKENS);
    broken.delete("--c-primary");
    expect(failingPairs(broken).join(" ")).toContain("missing token");
  });

  it("the caregiver and child thresholds differ", () => {
    expect(CAREGIVER_MIN_RATIO).toBe(4.5);
    expect(CHILD_MIN_RATIO).toBe(7);
  });
});
