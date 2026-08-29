/**
 * T12 §3 — "the progress range NEVER widens".
 *
 * The Playwright version records every value rendered during a real assessment.
 * This version proves the rule holds for every estimate the engine could
 * possibly emit, including the adversarial ones a scripted browser run would
 * never produce.
 */
import { describe, expect, it } from "vitest";

import {
  ZERO,
  firstWidening,
  fraction,
  narrow,
  rangeCopyKey,
  start,
  width,
  type Range,
} from "./progress-range";

describe("narrowing", () => {
  it("shrinks the ceiling when the engine says fewer questions remain", () => {
    const first = start(20, 55);
    const second = narrow(first, { answered: 1, minRemaining: 19, maxRemaining: 48 });
    expect(second.maxRemaining).toBe(48);
    expect(second.answered).toBe(1);
  });

  it("REFUSES to raise the ceiling when the engine says more remain", () => {
    // The assessment may genuinely take longer. The caregiver finds that out by
    // it finishing later, not by watching the end move away from them twenty
    // minutes into answering questions about their own child.
    const first = start(20, 40);
    const second = narrow(first, { answered: 1, minRemaining: 20, maxRemaining: 55 });
    expect(second.maxRemaining).toBe(40);
  });

  it("raises the floor but never past the ceiling", () => {
    const first = start(5, 30);
    const second = narrow(first, { answered: 1, minRemaining: 40, maxRemaining: 12 });
    expect(second.maxRemaining).toBe(12);
    expect(second.minRemaining).toBe(12);
    expect(width(second)).toBe(0);
  });

  it("never lets the answered count go backwards", () => {
    const first: Range = { answered: 10, minRemaining: 2, maxRemaining: 8 };
    expect(narrow(first, { answered: 3, minRemaining: 2, maxRemaining: 8 }).answered).toBe(10);
  });

  it("clamps negatives out of an engine that returned nonsense", () => {
    const result = narrow(start(0, 10), { answered: 1, minRemaining: -5, maxRemaining: -3 });
    expect(result.minRemaining).toBe(0);
    expect(result.maxRemaining).toBe(0);
  });
});

describe("monotonicity over a whole assessment", () => {
  it("holds for a realistic adaptive sequence", () => {
    const history: Range[] = [start(20, 55)];
    // The engine's own estimate wanders in both directions, as an adaptive
    // engine's does. The display must not.
    const estimates = [50, 52, 45, 47, 40, 44, 31, 33, 20, 24, 12, 9, 5, 6, 2, 0];
    for (const [index, remaining] of estimates.entries()) {
      history.push(
        narrow(history[history.length - 1]!, {
          answered: index + 1,
          minRemaining: Math.max(0, remaining - 8),
          maxRemaining: remaining,
        }),
      );
    }
    expect(firstWidening(history)).toBe(-1);
    expect(history[history.length - 1]!.maxRemaining).toBe(0);
    expect(fraction(history[history.length - 1]!)).toBe(1);
  });

  it("holds even when every estimate tries to widen", () => {
    const history: Range[] = [start(10, 30)];
    for (let index = 1; index <= 30; index += 1) {
      history.push(
        narrow(history[history.length - 1]!, {
          answered: index,
          minRemaining: 0,
          maxRemaining: 30 + index * 5,
        }),
      );
    }
    expect(firstWidening(history)).toBe(-1);
  });

  it("the detector actually detects a widening", () => {
    // A monotonicity check that cannot fail proves nothing about the runs that
    // passed.
    const bad: Range[] = [
      { answered: 1, minRemaining: 5, maxRemaining: 10 },
      { answered: 2, minRemaining: 5, maxRemaining: 20 },
    ];
    expect(firstWidening(bad)).toBe(1);
  });

  it("the detector catches a fraction that goes backwards", () => {
    const bad: Range[] = [
      { answered: 5, minRemaining: 0, maxRemaining: 5 },
      { answered: 5, minRemaining: 0, maxRemaining: 15 },
    ];
    expect(firstWidening(bad)).toBe(1);
  });
});

describe("fraction", () => {
  it("is zero before anything is answered and one at the end", () => {
    expect(fraction(ZERO)).toBe(0);
    expect(fraction(start(0, 40))).toBe(0);
    expect(fraction({ answered: 40, minRemaining: 0, maxRemaining: 0 })).toBe(1);
  });

  it("uses the pessimistic end so it cannot overshoot and snap back", () => {
    expect(fraction({ answered: 10, minRemaining: 0, maxRemaining: 30 })).toBeCloseTo(0.25);
  });
});

describe("copy keys", () => {
  it("never returns rendered Arabic", () => {
    // The API and this module both emit keys, so every caregiver-facing string
    // stays inside the i18n bundle and inside the banned-terms lint.
    expect(rangeCopyKey({ answered: 5, minRemaining: 0, maxRemaining: 0 })).toBe(
      "assessment.progress.done",
    );
    expect(rangeCopyKey({ answered: 5, minRemaining: 3, maxRemaining: 3 })).toBe(
      "assessment.progress.exact",
    );
    expect(rangeCopyKey({ answered: 5, minRemaining: 3, maxRemaining: 9 })).toBe(
      "assessment.progress.range",
    );
  });
});
