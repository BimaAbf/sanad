/**
 * T13 §20 — "the prompt ladder always terminates in success within 4 rungs".
 *
 * That is the property the whole child app rests on: because the ladder always
 * ends in a success, there is no failure state, and because there is no failure
 * state the product never has to decide how to tell a child they were wrong.
 */
import { describe, expect, it } from "vitest";

import { DEFAULT_WAIT_MS, MAX_WAIT_MS, MIN_WAIT_MS } from "./interaction";
import {
  AUTO_SELECT_DELAY_MS,
  RUNGS,
  buildLadder,
  recordedPromptLevel,
  rungAt,
  terminatesInSuccess,
  worstCaseDurationMs,
} from "./prompt-ladder";

describe("the ladder", () => {
  it("has exactly four rungs, ending in full_model", () => {
    expect(RUNGS).toEqual(["initial", "gestural", "partial_verbal", "full_model"]);
    const ladder = buildLadder(DEFAULT_WAIT_MS);
    expect(ladder).toHaveLength(4);
    expect(ladder[3]!.rung).toBe("full_model");
  });

  it("fires at 0, wait, 2x wait and 3x wait", () => {
    const ladder = buildLadder(8000);
    expect(ladder.map((rung) => rung.atMs)).toEqual([0, 8000, 16000, 24000]);
  });

  it("scales entirely with the child's wait time", () => {
    // wait_time_ms is the one number a caregiver is asked to tune. It has to
    // move the whole sequence, not only the first step.
    const slow = buildLadder(20000);
    expect(slow.map((rung) => rung.atMs)).toEqual([0, 20000, 40000, 60000]);
  });

  it("repeats the instruction identically at the second rung", () => {
    // docs/04e §C13: identical repetition. A rephrased instruction is a new
    // comprehension task at the moment the child is already struggling.
    const ladder = buildLadder(DEFAULT_WAIT_MS);
    expect(ladder[1]!.audio).toBe("instruction");
    expect(ladder[0]!.audio).toBe("instruction");
  });

  it("only the last rung auto-selects", () => {
    const ladder = buildLadder(DEFAULT_WAIT_MS);
    expect(ladder.slice(0, 3).every((rung) => rung.autoSelectAfterMs === null)).toBe(true);
    expect(ladder[3]!.autoSelectAfterMs).toBe(AUTO_SELECT_DELAY_MS);
  });

  it("terminates in a success at every legal wait time", () => {
    for (let wait = MIN_WAIT_MS; wait <= MAX_WAIT_MS; wait += 500) {
      expect(terminatesInSuccess(wait), `wait=${wait}`).toBe(true);
    }
  });

  it("never exceeds the animation limits at any rung", () => {
    for (const rung of buildLadder(DEFAULT_WAIT_MS)) {
      expect(rung.pulseHz).toBeLessThanOrEqual(3);
    }
  });
});

describe("rungAt", () => {
  const wait = 8000;

  it("returns the initial rung before the first wait elapses", () => {
    expect(rungAt(0, wait).rung).toBe("initial");
    expect(rungAt(7999, wait).rung).toBe("initial");
  });

  it("advances exactly on the boundary", () => {
    expect(rungAt(8000, wait).rung).toBe("gestural");
    expect(rungAt(16000, wait).rung).toBe("partial_verbal");
    expect(rungAt(24000, wait).rung).toBe("full_model");
  });

  it("never returns null, however long the child takes", () => {
    // A child who sits for ten minutes is not in an undefined state. They are
    // at full_model, which auto-selects, which is a success.
    expect(rungAt(600_000, wait).rung).toBe("full_model");
  });
});

describe("session planning", () => {
  it("sizes an activity by its worst case, not its best", () => {
    // 25 seconds at the default. Planning an 8-minute session as if every
    // activity takes 8 seconds is how a session overruns a child's attention.
    expect(worstCaseDurationMs(8000)).toBe(25_500);
  });
});

describe("what is recorded", () => {
  it("maps the first rung to independent and the rest to themselves", () => {
    expect(recordedPromptLevel("initial")).toBe("independent");
    expect(recordedPromptLevel("gestural")).toBe("gestural");
    expect(recordedPromptLevel("partial_verbal")).toBe("partial_verbal");
    expect(recordedPromptLevel("full_model")).toBe("full_model");
  });

  it("uses the same vocabulary as the API's prompt_level enum", () => {
    // A mismatch here is a 422 on every prompted attempt, which is exactly the
    // attempts a struggling child produces.
    const apiEnum = ["independent", "gestural", "partial_verbal", "full_model"];
    expect(RUNGS.map(recordedPromptLevel).sort()).toEqual([...apiEnum].sort());
  });
});
