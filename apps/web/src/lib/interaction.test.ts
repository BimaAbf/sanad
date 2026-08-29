/**
 * T13 — the child app's interaction contract.
 *
 * These are the requirements that ARE the functional requirements (docs/09
 * P13). Playwright checks them in a rendered browser; this file checks the
 * numbers themselves, because a Playwright suite that cannot run — no browser
 * installed, CI not yet green — must not be the only thing standing between a
 * child and a 44-pixel button.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import {
  BUDGETS,
  CALM_MODE_INTER_ACTIVITY_MS,
  DEFAULT_CHOICES,
  DEFAULT_PROFILE,
  DEFAULT_WAIT_MS,
  DOUBLE_TAP_TOLERANCE_MS,
  INTER_ACTIVITY_CALM_MS,
  MAX_ANIMATION_HZ,
  MAX_ANIMATION_MS,
  MAX_INSTRUCTION_WORDS,
  PULSE_HZ,
  TOUCH_GAP_PX,
  TOUCH_TARGET_PX,
  VAD,
  animationIsSafe,
  clampChoices,
  clampWait,
  instructionIsShortEnough,
  instructionWordCount,
  interActivityPauseMs,
  shouldCountTap,
} from "./interaction";

const DOCS = join(import.meta.dirname, "..", "..", "..", "..", "docs");

describe("touch targets", () => {
  it("uses 88px, the stricter of the two documented values", () => {
    // docs/04e §C13 says >= 80px; docs/06 §5 and docs/09 P13 say >= 88px.
    // Taking the larger cannot violate either.
    expect(TOUCH_TARGET_PX).toBe(88);
    expect(TOUCH_GAP_PX).toBe(20);
  });

  it("two targets plus a gap still fit a 320px viewport", () => {
    // The acceptance criterion asserts bounding boxes at 320px width. If the
    // arithmetic does not fit, no amount of CSS will make the assertion pass.
    const needed = TOUCH_TARGET_PX * 2 + TOUCH_GAP_PX;
    expect(needed).toBeLessThanOrEqual(320);
  });

  it("four targets do not fit side by side, so max_choices must wrap", () => {
    // Recorded rather than asserted as a failure: it is why the 4-choice layout
    // is a 2x2 grid and not a row. Discovering this in a browser is expensive.
    expect(TOUCH_TARGET_PX * 4 + TOUCH_GAP_PX * 3).toBeGreaterThan(320);
  });
});

describe("instructions", () => {
  it("counts words after substitution", () => {
    expect(instructionWordCount("وريني {label}", "الأحمر")).toBe(2);
    expect(instructionWordCount("وريني {label}", "كوباية مية")).toBe(3);
    expect(instructionWordCount("  وريني   {label}  ", "الأحمر")).toBe(2);
  });

  it("rejects an instruction over five words", () => {
    expect(MAX_INSTRUCTION_WORDS).toBe(5);
    expect(instructionIsShortEnough("وريني {label}", "الأحمر")).toBe(true);
    expect(instructionIsShortEnough("من فضلك ممكن تورّيني {label} دلوقتي", "الأحمر")).toBe(false);
  });

  it("every seeded instruction template fits after the longest label", () => {
    // The curriculum's longest label is "كوباية مية" (two words). A template
    // that fits one-word labels and not that one is a runtime failure on
    // exactly one skill, which is the kind that ships.
    const seed = readFileSync(
      join(DOCS, "..", "services", "api", "seeds", "curriculum.py"),
      "utf8",
    );
    // Line by line: a whole-file regex spans Python's triple-quoted strings
    // and captures a docstring as if it were an instruction.
    const templates = seed
      .split(/\r?\n/)
      .map((line) => /^\s*"([^"]*\{label\}[^"]*)",\s*$/.exec(line)?.[1])
      .filter((value): value is string => typeof value === "string");
    expect(templates.length).toBeGreaterThan(4);
    for (const template of templates) {
      expect(instructionIsShortEnough(template, "كوباية مية"), template).toBe(true);
    }
  });
});

describe("wait time", () => {
  it("defaults to 8 seconds and clamps to the documented range", () => {
    expect(DEFAULT_WAIT_MS).toBe(8000);
    expect(clampWait(500)).toBe(3000);
    expect(clampWait(99_000)).toBe(20_000);
    expect(clampWait(8000)).toBe(8000);
  });
});

describe("choices", () => {
  it("defaults to two and never exceeds four", () => {
    expect(DEFAULT_CHOICES).toBe(2);
    expect(clampChoices(1)).toBe(2);
    expect(clampChoices(9)).toBe(4);
    expect(clampChoices(3)).toBe(3);
  });
});

describe("animation", () => {
  it("caps frequency at 3Hz and duration at 400ms", () => {
    expect(MAX_ANIMATION_HZ).toBe(3);
    expect(MAX_ANIMATION_MS).toBe(400);
    expect(animationIsSafe(1.5, 400)).toBe(true);
    expect(animationIsSafe(3, 400)).toBe(true);
    expect(animationIsSafe(3.1, 400)).toBe(false);
    expect(animationIsSafe(2, 401)).toBe(false);
  });

  it("the ladder pulse is well under the seizure-risk ceiling", () => {
    // Elevated seizure risk in this population is the reason for the 3Hz cap;
    // 1.5Hz is half of it, and it is also simply calmer to look at.
    expect(PULSE_HZ).toBe(1.5);
    expect(animationIsSafe(PULSE_HZ, MAX_ANIMATION_MS)).toBe(true);
  });

  it("globals.css carries a prefers-reduced-motion override", () => {
    const css = readFileSync(
      join(import.meta.dirname, "..", "styles", "globals.css"),
      "utf8",
    );
    expect(css).toContain("prefers-reduced-motion: reduce");
    expect(css).toContain("animation-duration: 0.01ms !important");
  });
});

describe("tap handling", () => {
  it("counts the first tap", () => {
    expect(shouldCountTap("card-1", 1000, null)).toBe(true);
  });

  it("ignores a repeat tap on the same target inside the tolerance", () => {
    const last = { target: "card-1", atMs: 1000 };
    expect(shouldCountTap("card-1", 1000 + DOUBLE_TAP_TOLERANCE_MS - 1, last)).toBe(false);
    expect(shouldCountTap("card-1", 1000 + DOUBLE_TAP_TOLERANCE_MS, last)).toBe(true);
  });

  it("always counts a tap on a different target", () => {
    // A child changing their mind is not a tremor, and it is not our place to
    // refuse the second answer.
    const last = { target: "card-1", atMs: 1000 };
    expect(shouldCountTap("card-2", 1001, last)).toBe(true);
  });

  it("uses the documented 400ms tolerance", () => {
    expect(DOUBLE_TAP_TOLERANCE_MS).toBe(400);
  });
});

describe("calm between activities", () => {
  it("is 800ms normally and longer in calm mode", () => {
    expect(INTER_ACTIVITY_CALM_MS).toBe(800);
    expect(CALM_MODE_INTER_ACTIVITY_MS).toBe(1200);
    expect(interActivityPauseMs(DEFAULT_PROFILE)).toBe(800);
    expect(interActivityPauseMs({ ...DEFAULT_PROFILE, calmMode: true })).toBe(1200);
  });
});

describe("VAD tuning", () => {
  it("matches the retuned values in docs/04d §3", () => {
    // Web defaults are 0.50 / 3 / 200ms / 8 frames. Every one of ours is looser,
    // because the default cuts these children off mid-word.
    expect(VAD.positiveSpeechThreshold).toBe(0.35);
    expect(VAD.minSpeechFrames).toBe(2);
    expect(VAD.preSpeechPadMs).toBe(500);
    expect(VAD.redemptionFrames).toBe(24);
    expect(VAD.maxDurationMs).toBe(6000);
  });

  it("the redemption window is around 750ms at 32ms frames", () => {
    // docs/04d calls getting this wrong "the most common way this feature
    // fails": at the default the recogniser cuts the child off and the platform
    // tells them they were wrong.
    const ms = VAD.redemptionFrames * 32;
    expect(ms).toBeGreaterThanOrEqual(700);
    expect(ms).toBeLessThanOrEqual(800);
  });
});

describe("performance budgets", () => {
  it("matches docs/06 §6", () => {
    expect(BUDGETS.caregiver.jsGzKb).toBe(180);
    expect(BUDGETS.caregiver.lcpMs).toBe(1800);
    expect(BUDGETS.caregiver.cls).toBe(0.05);
    expect(BUDGETS.child.jsGzKb).toBe(220);
    expect(BUDGETS.child.lcpMs).toBe(2200);
    expect(BUDGETS.child.cls).toBe(0.01);
    expect(BUDGETS.child.manifestMb).toBe(4);
  });
});
