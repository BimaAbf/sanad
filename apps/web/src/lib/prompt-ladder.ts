/**
 * The errorless prompt ladder, in UI terms.
 *
 * docs/06 §4 gives it as a timeline:
 *
 *     t=0          "وريني الأحمر"      audio + text + speaker icon
 *     t=+wait      identical audio, correct card pulses at 1.5 Hz
 *     t=+2*wait    partial verbal, correct card pulses and scales slightly
 *     t=+3*wait    full model, correct card lifts and glows, auto-selects at +1.5 s
 *                  → the child taps it → full celebration
 *
 * The child experiences four successes in a row over about 25 seconds. The
 * database records ONE `full_model` attempt that contributes almost nothing to
 * BKT. Honest measurement, kind presentation — and the two halves are separate
 * on purpose, so neither can be quietly traded for the other.
 *
 * The property that matters most: **the ladder always terminates in a success.**
 * There is no rung after `full_model`, and `full_model` auto-selects. A child
 * cannot reach a dead end by doing nothing, because doing nothing is a valid
 * way to answer.
 *
 * Pure. No React, no timers — the caller owns the clock.
 */

import { PULSE_HZ } from "./interaction";

export type Rung = "initial" | "gestural" | "partial_verbal" | "full_model";

/** The order is the ladder. Nothing follows `full_model`. */
export const RUNGS: readonly Rung[] = ["initial", "gestural", "partial_verbal", "full_model"];

/** docs/06 §4 — the pause before the auto-selection at the last rung. */
export const AUTO_SELECT_DELAY_MS = 1500;

export interface RungPresentation {
  rung: Rung;
  /** Milliseconds after the activity started that this rung fires. */
  atMs: number;
  /** Replay the same audio, or play a different clip. */
  audio: "instruction" | "partial" | "model";
  /** Visual support on the correct choice. */
  highlight: "none" | "pulse" | "pulse_scale" | "lift_glow";
  pulseHz: number;
  /** Only the last rung selects for the child. */
  autoSelectAfterMs: number | null;
}

/**
 * The whole ladder for one activity, given this child's wait time.
 *
 * Every rung is at a multiple of `waitMs` rather than at a fixed clock time,
 * because `child.wait_time_ms` is the one number a caregiver is asked to tune
 * and it has to move the entire sequence, not just the first step.
 */
export function buildLadder(waitMs: number): RungPresentation[] {
  return [
    {
      rung: "initial",
      atMs: 0,
      audio: "instruction",
      highlight: "none",
      pulseHz: 0,
      autoSelectAfterMs: null,
    },
    {
      rung: "gestural",
      atMs: waitMs,
      // Identical repetition, deliberately. docs/04e §C13: "one voice, one
      // speaking rate, identical repetition" — a rephrased instruction is a new
      // comprehension task at the moment the child is already struggling.
      audio: "instruction",
      highlight: "pulse",
      pulseHz: PULSE_HZ,
      autoSelectAfterMs: null,
    },
    {
      rung: "partial_verbal",
      atMs: waitMs * 2,
      audio: "partial",
      highlight: "pulse_scale",
      pulseHz: PULSE_HZ,
      autoSelectAfterMs: null,
    },
    {
      rung: "full_model",
      atMs: waitMs * 3,
      audio: "model",
      highlight: "lift_glow",
      pulseHz: PULSE_HZ,
      autoSelectAfterMs: AUTO_SELECT_DELAY_MS,
    },
  ];
}

/** Which rung is active at `elapsedMs`. Never returns null. */
export function rungAt(elapsedMs: number, waitMs: number): RungPresentation {
  const ladder = buildLadder(waitMs);
  let current = ladder[0]!;
  for (const step of ladder) {
    if (elapsedMs >= step.atMs) current = step;
  }
  return current;
}

/**
 * How long the whole ladder takes if the child never responds.
 *
 * Used by the session planner to size a session honestly: an activity that can
 * take 25 seconds must not be planned as if it takes 8.
 */
export function worstCaseDurationMs(waitMs: number): number {
  return waitMs * 3 + AUTO_SELECT_DELAY_MS;
}

/** The ladder always ends in a success. Asserted, not assumed. */
export function terminatesInSuccess(waitMs: number): boolean {
  const ladder = buildLadder(waitMs);
  const last = ladder[ladder.length - 1]!;
  return ladder.length <= 4 && last.rung === "full_model" && last.autoSelectAfterMs !== null;
}

/**
 * What is recorded for an attempt answered at this rung.
 *
 * `full_model` maps to a prompt level that BKT discounts to zero — the answer
 * was given to the child, so it says nothing about what they know. It is still
 * recorded, because a session made entirely of full models is a signal a
 * caregiver needs to see.
 */
export function recordedPromptLevel(rung: Rung): string {
  return rung === "initial" ? "independent" : rung;
}
