/**
 * The child session as an explicit state machine.
 *
 * It exists because of one class of bug the previous play screen had, and the
 * bug is worth naming: a component that owned a `celebrating` boolean, a
 * `chosenId` and a `phase` could hold `correct = false` and `celebrating =
 * true` at the same time, and did — it celebrated on every tap before any
 * server round trip. Contradictory states are impossible here because there is
 * one state, it is a tagged union, and there is nowhere to put a celebration
 * that is not attached to a verdict the server sent.
 *
 *      LOADING ──▶ INSTRUCTION ──▶ READY ──▶ ANSWERING ──▶ SUBMITTING
 *                                    ▲                          │
 *                                    │                          ▼
 *                              RETRY / SUPPORT ◀────────────  RESULT
 *                                                               │
 *                                                               ▼
 *                                                            CLOSING
 *
 * `SUBMITTING` is a state and not a flag for the same reason: while it holds,
 * `canAnswer` is false, so a second tap cannot start a second submission. The
 * idempotency key is the server-side backstop; this is the client-side one, and
 * a child tapping a card four times in a second needs both.
 *
 * Pure. No React, no fetch, no timers — `reduce` is a function of the state and
 * one event, so every path below is reachable from a test.
 */

import type { Activity, AnswerResult, SessionResult } from "@/lib/tutor";

export type Phase =
  | "idle"
  | "loading"
  | "instruction"
  | "ready"
  | "answering"
  | "submitting"
  | "result"
  | "error"
  | "closing"
  | "finished";

/** What the child is looking at, and why. */
export type MachineState =
  | { phase: "idle" }
  | { phase: "loading" }
  | { phase: "instruction"; activity: Activity }
  | { phase: "ready"; activity: Activity }
  | { phase: "answering"; activity: Activity; draft: unknown }
  | { phase: "submitting"; activity: Activity }
  | { phase: "result"; activity: Activity; result: AnswerResult }
  /**
   * Recoverable. The session has NOT finished — the specification is explicit
   * that a failed "next activity" request must not end a child's session.
   */
  | { phase: "error"; activity: Activity | null; messageAr: string | null }
  | { phase: "closing" }
  | { phase: "finished"; summary: SessionResult | null };

export type MachineEvent =
  | { type: "START" }
  | { type: "ACTIVITY_LOADED"; activity: Activity }
  | { type: "SESSION_OVER" }
  | { type: "INSTRUCTION_DONE" }
  | { type: "DRAFT"; draft: unknown }
  | { type: "SUBMIT" }
  | { type: "RESULT"; result: AnswerResult }
  | { type: "CONTINUE" }
  | { type: "ERROR"; messageAr: string | null }
  | { type: "RETRY" }
  | { type: "CLOSING" }
  | { type: "CLOSED"; summary: SessionResult | null };

export const INITIAL: MachineState = { phase: "idle" };

/**
 * The activity the machine currently holds, if any. Used by the shell to keep
 * rendering the same screen through a submission rather than blanking it.
 */
export function currentActivity(state: MachineState): Activity | null {
  switch (state.phase) {
    case "instruction":
    case "ready":
    case "answering":
    case "submitting":
    case "result":
      return state.activity;
    case "error":
      return state.activity;
    default:
      return null;
  }
}

/** Whether a tap on a choice should do anything at all. */
export function canAnswer(state: MachineState): boolean {
  return state.phase === "ready" || state.phase === "answering";
}

/**
 * Whether to celebrate.
 *
 * The ONLY place in the client that answers this question, and it answers it
 * from `result.correct` — the server's verdict — and from nothing else. There
 * is no branch here on what the child tapped, because the client does not know
 * which option was right.
 */
export function shouldCelebrate(state: MachineState): boolean {
  return state.phase === "result" && state.result.correct;
}

/**
 * Whether the child is being asked to try again.
 *
 * Distinct from "wrong": an uncertain speech attempt lands here too, and the
 * screen for it is the same encouraging screen — there is no failure state.
 */
export function shouldRetry(state: MachineState): boolean {
  return state.phase === "result" && !state.result.correct;
}

export function reduce(state: MachineState, event: MachineEvent): MachineState {
  switch (event.type) {
    case "START":
      return { phase: "loading" };

    case "ACTIVITY_LOADED":
      // An instruction is spoken before the child may answer, always. Landing
      // in `ready` directly would let a fast tap answer a question the child
      // has not heard.
      return { phase: "instruction", activity: event.activity };

    case "SESSION_OVER":
      return { phase: "closing" };

    case "INSTRUCTION_DONE":
      return state.phase === "instruction"
        ? { phase: "ready", activity: state.activity }
        : state;

    case "DRAFT":
      // Sorting and sequencing are built up before they are submitted. A draft
      // outside an answerable phase is a stale event from a component that has
      // already been replaced, and is dropped rather than reviving the screen.
      return canAnswer(state) && currentActivity(state)
        ? { phase: "answering", activity: currentActivity(state)!, draft: event.draft }
        : state;

    case "SUBMIT": {
      const activity = currentActivity(state);
      // The guard that makes a double tap impossible on the client. Not a
      // replacement for the idempotency key — a network retry never reaches
      // this code at all — but the one that stops the second tap costing a
      // round trip.
      if (!canAnswer(state) || !activity) return state;
      return { phase: "submitting", activity };
    }

    case "RESULT":
      return state.phase === "submitting"
        ? { phase: "result", activity: state.activity, result: event.result }
        : state;

    case "CONTINUE":
      return state.phase === "result" ? { phase: "loading" } : state;

    case "ERROR":
      // Recoverable by construction: the activity is kept, so `RETRY` puts the
      // child back in front of the same question rather than ending the
      // session or starting a different one.
      return {
        phase: "error",
        activity: currentActivity(state),
        messageAr: event.messageAr,
      };

    case "RETRY": {
      if (state.phase !== "error") return state;
      return state.activity
        ? { phase: "ready", activity: state.activity }
        : { phase: "loading" };
    }

    case "CLOSING":
      return { phase: "closing" };

    case "CLOSED":
      return { phase: "finished", summary: event.summary };

    default:
      return state;
  }
}

/**
 * The contradictory states the machine must never be able to hold.
 *
 * Written as a checkable predicate rather than as prose so the test can assert
 * it over every state reachable from every event, instead of over the three
 * someone thought of.
 */
export function isContradictory(state: MachineState): boolean {
  if (state.phase === "result") {
    // A celebration with no verdict, or a verdict that says both things.
    return shouldCelebrate(state) === shouldRetry(state);
  }
  if (state.phase === "submitting") {
    // Answering while a submission is in flight.
    return canAnswer(state);
  }
  if (state.phase === "finished") {
    return false;
  }
  // Celebrating anywhere other than on a result.
  return shouldCelebrate(state) || shouldRetry(state);
}
