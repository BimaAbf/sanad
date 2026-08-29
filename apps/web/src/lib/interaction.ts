/**
 * The child app's interaction contract, as code.
 *
 * docs/04e §C13 heads its table with "these are requirements, not preferences",
 * and docs/09 P13 says "this is the component where the accessibility
 * requirements ARE the functional requirements". So they live here as constants
 * with tests against them, rather than as numbers scattered through JSX where a
 * refactor can quietly change one.
 *
 * Where docs/04e and docs/06 disagree, the STRICTER value wins and the
 * disagreement is recorded — see TOUCH_TARGET_PX.
 *
 * Pure. No React, no DOM.
 */

/**
 * Minimum touch target for the child app, in CSS pixels.
 *
 * docs/04e §C13 says ">= 80 x 80 px, >= 16 px gap".
 * docs/06 §4 and docs/09 P13 say ">= 88 x 88px with >= 20px gaps".
 *
 * The larger pair is used. The two documents were written to the same intent
 * and one of them is a later revision; taking the stricter value cannot violate
 * either, and the acceptance criterion in docs/09 P13 — which is what CI
 * asserts — names 88.
 */
export const TOUCH_TARGET_PX = 88;
export const TOUCH_GAP_PX = 20;

/** Caregiver app. docs/06 §5. */
export const CAREGIVER_TOUCH_TARGET_PX = 48;

/** docs/06 §4 — after {label} substitution. */
export const MAX_INSTRUCTION_WORDS = 5;

/** docs/04e §C13 — `child.wait_time_ms`, adjustable 3000–20000. */
export const DEFAULT_WAIT_MS = 8000;
export const MIN_WAIT_MS = 3000;
export const MAX_WAIT_MS = 20000;

/** docs/06 §4 — no animation faster than this, or longer than that. */
export const MAX_ANIMATION_HZ = 3;
export const MAX_ANIMATION_MS = 400;

/** The gentle pulse on the correct choice at ladder rung 2. */
export const PULSE_HZ = 1.5;

/** docs/04e §C13 — tremor and perseveration must not register as two answers. */
export const DOUBLE_TAP_TOLERANCE_MS = 400;

/** docs/06 §4 — processing time between activities. */
export const INTER_ACTIVITY_CALM_MS = 800;

/** docs/09 P13 — calm mode lengthens that pause. */
export const CALM_MODE_INTER_ACTIVITY_MS = 1200;

/** docs/04e §C13 — 2 by default; 3–4 only at `practising` or better. */
export const DEFAULT_CHOICES = 2;
export const MAX_CHOICES = 4;

/** docs/04d §3 VAD table, retuned for this population. */
export const VAD = {
  positiveSpeechThreshold: 0.35,
  minSpeechFrames: 2,
  preSpeechPadMs: 500,
  redemptionFrames: 24,
  maxDurationMs: 6000,
} as const;

/** docs/06 §6 — hard CI budgets, not warnings. */
export const BUDGETS = {
  caregiver: { jsGzKb: 180, lcpMs: 1800, inpMs: 200, cls: 0.05 },
  child: { jsGzKb: 220, lcpMs: 2200, inpMs: 150, cls: 0.01, manifestMb: 4 },
} as const;

export interface AccessibilityProfile {
  waitTimeMs: number;
  maxChoices: number;
  audioRatePct: number;
  calmMode: boolean;
}

export const DEFAULT_PROFILE: AccessibilityProfile = {
  waitTimeMs: DEFAULT_WAIT_MS,
  maxChoices: DEFAULT_CHOICES,
  audioRatePct: 85,
  calmMode: false,
};

export function clampWait(ms: number): number {
  return Math.min(MAX_WAIT_MS, Math.max(MIN_WAIT_MS, ms));
}

export function clampChoices(count: number): number {
  return Math.min(MAX_CHOICES, Math.max(2, count));
}

export function interActivityPauseMs(profile: AccessibilityProfile): number {
  return profile.calmMode ? CALM_MODE_INTER_ACTIVITY_MS : INTER_ACTIVITY_CALM_MS;
}

/** True when an animation is within both the frequency and duration limits. */
export function animationIsSafe(hz: number, durationMs: number): boolean {
  return hz <= MAX_ANIMATION_HZ && durationMs <= MAX_ANIMATION_MS;
}

export function instructionWordCount(instruction: string, label: string): number {
  return instruction
    .replace("{label}", label)
    .trim()
    .split(/\s+/)
    .filter(Boolean).length;
}

export function instructionIsShortEnough(instruction: string, label: string): boolean {
  return instructionWordCount(instruction, label) <= MAX_INSTRUCTION_WORDS;
}

/**
 * Tap de-bouncing.
 *
 * Returns true when this tap should be counted. A tap on the same target within
 * the tolerance of the previous one is a tremor, not an answer; a tap on a
 * *different* target always counts, because that is a child changing their mind
 * and it is not our place to refuse it.
 */
export function shouldCountTap(
  target: string,
  nowMs: number,
  last: { target: string; atMs: number } | null,
): boolean {
  if (last === null) return true;
  if (last.target !== target) return true;
  return nowMs - last.atMs >= DOUBLE_TAP_TOLERANCE_MS;
}
