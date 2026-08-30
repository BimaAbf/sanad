import { describe, expect, it } from "vitest";

import {
  INITIAL,
  canAnswer,
  currentActivity,
  isContradictory,
  reduce,
  shouldCelebrate,
  shouldRetry,
  type MachineEvent,
  type MachineState,
} from "@/lib/activity-machine";
import type { Activity, AnswerResult } from "@/lib/tutor";

/**
 * The client-side half of "no false success".
 *
 * The old play screen celebrated on every tap, before any round trip, because
 * `celebrating` was a boolean a component could set. These tests exist to say
 * that cannot happen here: the celebration is derived from a server verdict, it
 * is derivable in exactly one state, and no sequence of events reaches a state
 * where it disagrees with itself.
 */

const ACTIVITY: Activity = {
  session_finished: false,
  activity_id: "11111111-1111-4111-8111-111111111111",
  ordinal: 1,
  activity_type: "select_picture",
  skill_code: "color_red",
  difficulty: 1,
  modality: "receptive",
  strategy: "demonstrate_then_test",
  support_level: "high",
  choice_count: 2,
  presentation: {
    instruction_ar: "وريني أحمر",
    spoken_ar: "أحمر",
    demonstration_ar: "",
    options: [],
    bins: [],
    sample: null,
    glyph_ar: "",
    reference_path: [],
    object_count: 0,
    target_word_ar: "",
    caregiver_confirm_allowed: true,
    hide_labels: false,
  },
  wait_time_ms: 8000,
  decision_source: "deterministic_fallback",
  reason_codes: ["LOW_MASTERY"],
  guardrail_actions: [],
};

function result(overrides: Partial<AnswerResult> = {}): AnswerResult {
  return {
    activity_id: ACTIVITY.activity_id as string,
    correct: true,
    outcome: "correct",
    next_action: "next",
    support_action: "none",
    reward_delta: 2,
    stars_total: 2,
    achievements_unlocked: [],
    duplicate: false,
    score: null,
    threshold: null,
    detail: {},
    mastery_before: 0.15,
    mastery_after: 0.34,
    mastery_state: "introduced",
    ...overrides,
  };
}

function walk(events: MachineEvent[], from: MachineState = INITIAL): MachineState {
  return events.reduce(reduce, from);
}

const READY = walk([{ type: "START" }, { type: "ACTIVITY_LOADED", activity: ACTIVITY }, { type: "INSTRUCTION_DONE" }]);

describe("the happy path", () => {
  it("walks loading -> instruction -> ready -> submitting -> result", () => {
    expect(reduce(INITIAL, { type: "START" }).phase).toBe("loading");
    const loaded = walk([{ type: "START" }, { type: "ACTIVITY_LOADED", activity: ACTIVITY }]);
    expect(loaded.phase).toBe("instruction");
    expect(reduce(loaded, { type: "INSTRUCTION_DONE" }).phase).toBe("ready");
    const submitting = reduce(READY, { type: "SUBMIT" });
    expect(submitting.phase).toBe("submitting");
    expect(reduce(submitting, { type: "RESULT", result: result() }).phase).toBe("result");
  });

  it("speaks the instruction before the child may answer", () => {
    // Landing in `ready` directly would let a fast tap answer a question the
    // child has not heard.
    const loaded = walk([{ type: "START" }, { type: "ACTIVITY_LOADED", activity: ACTIVITY }]);
    expect(canAnswer(loaded)).toBe(false);
    expect(canAnswer(reduce(loaded, { type: "INSTRUCTION_DONE" }))).toBe(true);
  });

  it("goes back to loading when the result is acknowledged", () => {
    const state = reduce(
      reduce(READY, { type: "SUBMIT" }),
      { type: "RESULT", result: result() },
    );
    expect(reduce(state, { type: "CONTINUE" }).phase).toBe("loading");
  });
});

describe("no false success", () => {
  it("celebrates only when the server said the answer was correct", () => {
    const wrong = walk(
      [{ type: "SUBMIT" }, { type: "RESULT", result: result({ correct: false, outcome: "incorrect" }) }],
      READY,
    );
    expect(shouldCelebrate(wrong)).toBe(false);
    expect(shouldRetry(wrong)).toBe(true);
  });

  it("does not celebrate an uncertain speech attempt either", () => {
    const unclear = walk(
      [
        { type: "SUBMIT" },
        {
          type: "RESULT",
          result: result({ correct: false, outcome: "uncertain", reward_delta: 0 }),
        },
      ],
      READY,
    );
    expect(shouldCelebrate(unclear)).toBe(false);
    expect(shouldRetry(unclear)).toBe(true);
  });

  it("never celebrates in any state that is not a result", () => {
    const states: MachineState[] = [
      INITIAL,
      { phase: "loading" },
      { phase: "instruction", activity: ACTIVITY },
      READY,
      { phase: "submitting", activity: ACTIVITY },
      { phase: "error", activity: ACTIVITY, messageAr: null },
      { phase: "closing" },
      { phase: "finished", summary: null },
    ];
    for (const state of states) {
      expect(shouldCelebrate(state)).toBe(false);
      expect(shouldRetry(state)).toBe(false);
    }
  });

  it("cannot reach a contradictory state from any sequence of events", () => {
    // The exhaustive version of the claim: every event applied to every state
    // reachable in three steps, and none of them contradicts itself.
    const events: MachineEvent[] = [
      { type: "START" },
      { type: "ACTIVITY_LOADED", activity: ACTIVITY },
      { type: "SESSION_OVER" },
      { type: "INSTRUCTION_DONE" },
      { type: "DRAFT", draft: { a: 1 } },
      { type: "SUBMIT" },
      { type: "RESULT", result: result() },
      { type: "RESULT", result: result({ correct: false, outcome: "incorrect" }) },
      { type: "CONTINUE" },
      { type: "ERROR", messageAr: null },
      { type: "RETRY" },
      { type: "CLOSING" },
      { type: "CLOSED", summary: null },
    ];

    let frontier: MachineState[] = [INITIAL];
    for (let depth = 0; depth < 3; depth += 1) {
      const next: MachineState[] = [];
      for (const state of frontier) {
        for (const event of events) {
          const after = reduce(state, event);
          expect(isContradictory(after)).toBe(false);
          next.push(after);
        }
      }
      frontier = next;
    }
  });
});

describe("double submission", () => {
  it("ignores a second SUBMIT while one is in flight", () => {
    const submitting = reduce(READY, { type: "SUBMIT" });
    expect(reduce(submitting, { type: "SUBMIT" })).toBe(submitting);
    expect(canAnswer(submitting)).toBe(false);
  });

  it("ignores a SUBMIT before the instruction has been heard", () => {
    const loaded = walk([{ type: "START" }, { type: "ACTIVITY_LOADED", activity: ACTIVITY }]);
    expect(reduce(loaded, { type: "SUBMIT" })).toBe(loaded);
  });

  it("ignores a RESULT that does not answer a submission in flight", () => {
    // A late response to a submission the machine has already moved past. It
    // must not put a verdict back on screen under a different activity.
    expect(reduce(READY, { type: "RESULT", result: result() })).toBe(READY);
  });

  it("ignores a draft from a component that has already been replaced", () => {
    const closing: MachineState = { phase: "closing" };
    expect(reduce(closing, { type: "DRAFT", draft: 1 })).toBe(closing);
  });
});

describe("errors are recoverable and do not end the session", () => {
  it("keeps the activity so RETRY puts the child back in front of it", () => {
    const failed = reduce(reduce(READY, { type: "SUBMIT" }), {
      type: "ERROR",
      messageAr: null,
    });
    expect(failed.phase).toBe("error");
    expect(currentActivity(failed)).toEqual(ACTIVITY);
    const retried = reduce(failed, { type: "RETRY" });
    expect(retried.phase).toBe("ready");
    expect(currentActivity(retried)).toEqual(ACTIVITY);
  });

  it("asks for a new activity when the failure was in fetching one", () => {
    const failed = reduce({ phase: "loading" }, { type: "ERROR", messageAr: null });
    expect(currentActivity(failed)).toBeNull();
    expect(reduce(failed, { type: "RETRY" }).phase).toBe("loading");
  });

  it("does not finish the session on a failed request", () => {
    const failed = reduce(READY, { type: "ERROR", messageAr: "مش قادرين" });
    expect(failed.phase).not.toBe("finished");
    expect(failed.phase).not.toBe("closing");
  });

  it("carries the server's own Arabic when there is any", () => {
    const failed = reduce(READY, { type: "ERROR", messageAr: "الجلسة خلصت" });
    expect(failed.phase === "error" && failed.messageAr).toBe("الجلسة خلصت");
  });
});

describe("finishing", () => {
  it("ends when the server says there is nothing more to deliver", () => {
    expect(reduce({ phase: "loading" }, { type: "SESSION_OVER" }).phase).toBe("closing");
  });

  it("carries the summary through to the closing screen", () => {
    const summary = {
      session_id: "s",
      ended_at: "2026-01-01T00:00:00Z",
      activities_completed: 4,
      correct: 3,
      incorrect: 1,
      no_response: 0,
      independent_responses: 2,
      supported_responses: 1,
      skills_practised: ["color_red"],
      skills_practised_ar: ["أحمر"],
      activity_types: ["select_picture"],
      mastery_changes: [],
      stars_earned: 5,
      stars_total: 12,
      achievements_unlocked: ["first_session"],
      duration_minutes: 5,
      best_streak: 2,
      went_well_ar: ["أحمر"],
      needs_practice_ar: [],
      narrative_ar: "لعبنا 4 ألعاب.",
      narrative_source: "template",
    };
    const finished = reduce({ phase: "closing" }, { type: "CLOSED", summary });
    expect(finished.phase === "finished" && finished.summary?.stars_total).toBe(12);
  });

  it("finishes even when the closing call failed", () => {
    // A summary that never arrived is a closing screen with no skill list, not
    // a session that refuses to end.
    const finished = reduce({ phase: "closing" }, { type: "CLOSED", summary: null });
    expect(finished.phase).toBe("finished");
  });
});
