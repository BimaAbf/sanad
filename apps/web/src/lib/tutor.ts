/**
 * The tutor loop's wire types and its client.
 *
 * Transcribed from `services/api/app/modules/tutor/schemas.py`, field for
 * field, so a drift between the two is a compile error here rather than an
 * `undefined` at render time.
 *
 * **There is no `correct` field on anything the client receives before it
 * answers.** `Presentation` has options, bins, a glyph and a reference path;
 * it has no answer, because the answer lives in a column the serialiser never
 * touches. That is not a convention this file follows — it is the reason this
 * file cannot decide whether a child was right even if someone asked it to.
 *
 * Every function here returns a discriminated result rather than throwing.
 * There is no failure state on the child surface (docs/04e §C13), and the
 * caller needs to tell "the server said no" from "the request never arrived":
 * the first ends the session cleanly, the second is worth retrying.
 */

export type ActivityType =
  | "select_picture"
  | "count_objects"
  | "match_pair"
  | "listen_choose"
  | "speak_word"
  | "sort_category"
  | "order_sequence"
  | "trace_letter";

export type Outcome = "correct" | "incorrect" | "uncertain" | "no_response";
export type NextAction = "next" | "retry" | "support";
export type SupportAction = "none" | "demonstrate" | "caregiver_confirm" | "simplify";
export type PromptLevel = "independent" | "gestural" | "partial_verbal" | "full_model";

export interface TutorOption {
  option_id: string;
  skill_code: string;
  label_ar: string;
  alt_ar: string;
  category: string;
  repeat: number;
}

export interface TutorBin {
  bin_id: string;
  label_ar: string;
  art_skill_code: string;
}

export interface Presentation {
  instruction_ar: string;
  spoken_ar: string;
  /** Non-empty only when the decision asked for a demonstration. */
  demonstration_ar: string;
  options: TutorOption[];
  bins: TutorBin[];
  sample: TutorOption | null;
  glyph_ar: string;
  /** Strokes of points in a unit box, y down. The tracing guide. */
  reference_path: number[][][];
  object_count: number;
  target_word_ar: string;
  caregiver_confirm_allowed: boolean;
  /** Listening tasks hide the written labels — otherwise it is a reading task. */
  hide_labels: boolean;
}

export interface Activity {
  session_finished: boolean;
  activity_id: string | null;
  ordinal: number;
  activity_type: ActivityType | "";
  skill_code: string;
  difficulty: number;
  modality: string;
  strategy: string;
  support_level: string;
  choice_count: number;
  presentation: Presentation;
  wait_time_ms: number;
  /** `groq:live`, `anthropic:live` or `deterministic_fallback`. */
  decision_source: string;
  reason_codes: string[];
  guardrail_actions: string[];
}

export interface TutorSession {
  session_id: string;
  child_id: string;
  started_at: string;
  wait_time_ms: number;
  max_choices: number;
  audio_rate_pct: number;
  calm_mode: boolean;
}

export type ResponsePayload =
  | { kind: "choice"; option_id: string }
  | { kind: "count"; value: number }
  | { kind: "sort"; assignments: Record<string, string> }
  | { kind: "sequence"; order: string[] }
  | {
      kind: "speech";
      transcript: string;
      confidence: number;
      recogniser_available?: boolean;
      caregiver_confirmed?: boolean;
    }
  | { kind: "strokes"; strokes: number[][][]; width: number; height: number }
  | { kind: "no_response" };

export interface AnswerResult {
  activity_id: string;
  /** The authoritative verdict. The client renders it; it never computes one. */
  correct: boolean;
  outcome: Outcome;
  next_action: NextAction;
  support_action: SupportAction;
  reward_delta: number;
  stars_total: number;
  achievements_unlocked: string[];
  duplicate: boolean;
  score: number | null;
  threshold: number | null;
  detail: Record<string, unknown>;
  mastery_before: number | null;
  mastery_after: number | null;
  mastery_state: string;
}

export interface SessionResult {
  session_id: string;
  ended_at: string;
  activities_completed: number;
  correct: number;
  incorrect: number;
  no_response: number;
  independent_responses: number;
  supported_responses: number;
  skills_practised: string[];
  skills_practised_ar: string[];
  activity_types: string[];
  mastery_changes: { skill_code: string; skill_label_ar: string; from_state: string; to_state: string }[];
  stars_earned: number;
  stars_total: number;
  achievements_unlocked: string[];
  duration_minutes: number;
  best_streak: number;
  went_well_ar: string[];
  needs_practice_ar: string[];
  narrative_ar: string;
  narrative_source: string;
}

/** Everything that can come back from a call. Never a throw. */
export type Reply<T> =
  | { ok: true; value: T }
  | { ok: false; retryable: boolean; code: string; messageAr: string | null };

async function post<T>(path: string, body: unknown): Promise<Reply<T>> {
  let response: Response;
  try {
    response = await fetch(`/api/tutor/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    // The request never arrived. Retryable, and the caller shows the child
    // nothing at all while it retries.
    return { ok: false, retryable: true, code: "network_unavailable", messageAr: null };
  }

  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (response.ok) return { ok: true, value: payload as T };

  const problem = (payload ?? {}) as { code?: string; message_ar?: string };
  return {
    ok: false,
    // A 5xx or a 429 may work on the next try; a 4xx will not, and retrying it
    // forever is how a child ends up looking at a screen that never moves.
    retryable: response.status >= 500 || response.status === 429,
    code: problem.code ?? "unknown_error",
    messageAr: problem.message_ar ?? null,
  };
}

export const startSession = (childId: string): Promise<Reply<TutorSession>> =>
  post<TutorSession>("sessions", { child_id: childId });

export const nextActivity = (sessionId: string): Promise<Reply<Activity>> =>
  post<Activity>(`sessions/${sessionId}/next`, {});

export const submitResponse = (
  sessionId: string,
  input: {
    activityId: string;
    response: ResponsePayload;
    idempotencyKey: string;
    latencyMs: number;
    promptLevel: PromptLevel;
  },
): Promise<Reply<AnswerResult>> =>
  post<AnswerResult>(`sessions/${sessionId}/respond`, {
    activity_id: input.activityId,
    response: input.response,
    idempotency_key: input.idempotencyKey,
    latency_ms: input.latencyMs,
    prompt_level: input.promptLevel,
  });

export const endSession = (
  sessionId: string,
  minutes: number,
): Promise<Reply<SessionResult>> =>
  post<SessionResult>(`sessions/${sessionId}/end`, { reason: "completed", minutes });

/**
 * The key that makes a double tap one attempt and one star.
 *
 * Derived from the session and the activity rather than generated, so the SAME
 * response retried after a timeout carries the SAME key — which is the only
 * thing that makes the server's `ON CONFLICT DO NOTHING` do any work. A random
 * key per attempt would make every retry a new attempt.
 */
export const responseKey = (sessionId: string, activityId: string): string =>
  `${sessionId}:${activityId}`;
