/**
 * The PGEE runner's progress indicator.
 *
 * docs/04e §C12 asks for a "narrowing progress range, never a bar that can move
 * backwards". That is not a polish detail. The runner is adaptive — the number
 * of remaining questions genuinely changes as the engine narrows the basal and
 * ceiling — so a naive "question 12 of 40" counter would jump to "12 of 55" and
 * a parent twenty minutes into an assessment about their child would watch the
 * end move further away.
 *
 * So the indicator shows a RANGE, and the range only ever shrinks. This module
 * owns that monotonicity, and the Playwright test records every value it emits
 * during a full assessment and asserts it never widened.
 *
 * Pure. No React.
 */

export interface Range {
  /** Questions answered so far. */
  answered: number;
  /** Fewest questions the assessment could still take. */
  minRemaining: number;
  /** Most questions it could still take. */
  maxRemaining: number;
}

export const ZERO: Range = { answered: 0, minRemaining: 0, maxRemaining: 0 };

export function width(range: Range): number {
  return range.maxRemaining - range.minRemaining;
}

/** Fraction complete, using the pessimistic end. Never decreases. */
export function fraction(range: Range): number {
  const total = range.answered + range.maxRemaining;
  if (total <= 0) return 0;
  return Math.min(1, range.answered / total);
}

/**
 * Fold a fresh engine estimate into the displayed range.
 *
 * The engine's estimate is advisory; the display is authoritative and clamped:
 *
 * * `maxRemaining` may only fall. If the engine now thinks more questions are
 *   needed, the displayed ceiling stays where it was. The assessment may
 *   genuinely take longer — the caregiver finds that out by it finishing later,
 *   not by watching a number grow.
 * * `minRemaining` may only rise, and never past the ceiling.
 * * `answered` only ever increments.
 *
 * The engine's real estimate is still reported to telemetry; it is only the
 * *display* that is clamped, so a persistently under-estimating engine shows up
 * in the data rather than being hidden by this function.
 */
export function narrow(previous: Range, estimate: Range): Range {
  const answered = Math.max(previous.answered, estimate.answered);
  const maxRemaining = Math.max(0, Math.min(previous.maxRemaining, estimate.maxRemaining));
  const minRemaining = Math.max(
    0,
    Math.min(maxRemaining, Math.max(previous.minRemaining, estimate.minRemaining)),
  );
  return { answered, minRemaining, maxRemaining };
}

/** The first range, before any answer. */
export function start(minTotal: number, maxTotal: number): Range {
  return { answered: 0, minRemaining: Math.min(minTotal, maxTotal), maxRemaining: maxTotal };
}

/**
 * Did this sequence of displayed ranges ever widen?
 *
 * Returns the index of the first violation, or -1. Used by the Playwright test,
 * and exported so the same rule is checked in the unit suite rather than only
 * in a browser.
 */
export function firstWidening(history: readonly Range[]): number {
  for (let index = 1; index < history.length; index += 1) {
    const before = history[index - 1]!;
    const after = history[index]!;
    if (after.maxRemaining > before.maxRemaining) return index;
    if (width(after) > width(before)) return index;
    if (fraction(after) < fraction(before) - 1e-9) return index;
  }
  return -1;
}

/** Copy key for the range label. The API never sends rendered Arabic. */
export function rangeCopyKey(range: Range): string {
  if (range.maxRemaining === 0) return "assessment.progress.done";
  if (width(range) === 0) return "assessment.progress.exact";
  return "assessment.progress.range";
}
