/**
 * Typed reads. One function per endpoint the caregiver app actually renders.
 *
 * The types are transcribed from the API's own response models
 * (the `schemas.py` under each `services/api/app/modules` package), not
 * inferred, so a drift between
 * the two is a compile error here rather than an undefined at render time.
 */

import { apiFetch, apiFetchOrNull } from "@/lib/api";

export interface CaregiverChildLink {
  id: string;
  display_name: string;
  role: string;
}

export interface Me {
  id: string;
  display_name: string | null;
  phone_e164: string;
  email: string | null;
  relationship: string | null;
  governorate: string | null;
  locale: string;
  has_play_pin: boolean;
  children: CaregiverChildLink[];
}

export interface Child {
  id: string;
  display_name: string;
  name_vowelised: string | null;
  date_of_birth: string;
  sex: string;
  gestational_weeks: number | null;
  comms_level: string;
  chronological_months: number;
  corrected_months: number;
  wait_time_ms: number;
  max_choices: number;
  audio_rate_pct: number;
  calm_mode: boolean;
  session_minutes: number;
  hearing_aid: boolean;
  glasses: boolean;
  version: number;
  updated_at: string;
}

export interface ActivitySuggestion {
  activity_code: string;
  skill_id: string;
  label_ar: string;
}

export interface Today {
  date: string;
  sessions: number;
  minutes: number;
  attempts: number;
  streak_days: number;
  suggestion: ActivitySuggestion | null;
  /** Exactly 3 when present, never 1 or 2. The server will not send fewer. */
  revisit_plan: ActivitySuggestion[];
  regression_detected: boolean;
}

export interface SkillCard {
  skill_id: string;
  code: string;
  label_ar: string;
  category: string;
  state: string;
  p_known: number;
  due_at: string | null;
  last_seen_at: string | null;
}

/**
 * `SkillsResponse` groups server-side and sends the counts with it, so the
 * client renders the map without doing arithmetic on a child's data. The
 * grouping key is the `skill_category` enum.
 */
export interface Skills {
  total: number;
  mastered: number;
  practising: number;
  not_started: number;
  by_category: Record<string, SkillCard[]>;
}

export interface JourneyPoint {
  assessment_id: string;
  completed_at: string;
  skills_mastered: number;
}

export interface Journey {
  status: "ok" | "insufficient_data";
  points: JourneyPoint[];
  copy_key: string;
}

export const getMe = () => apiFetchOrNull<Me>("/me");

export const getChild = (childId: string) =>
  apiFetchOrNull<Child>(`/children/${childId}`);

export const getToday = (childId: string) =>
  apiFetchOrNull<Today>(`/children/${childId}/progress/today`);

export const getSkills = (childId: string) =>
  apiFetchOrNull<Skills>(`/children/${childId}/progress/skills`);

export const getJourney = (childId: string) =>
  apiFetchOrNull<Journey>(`/children/${childId}/progress/journey`);

/** Writes go through server actions, which want the throwing version. */
export const requestOtp = (phone_e164: string) =>
  apiFetch<Record<string, never>>("/auth/otp/request", {
    method: "POST",
    auth: false,
    body: { phone_e164 },
  });

export interface TokenResponse {
  access_token: string;
  expires_in: number;
  is_new_user?: boolean;
}

export const verifyOtp = (phone_e164: string, code: string) =>
  apiFetch<TokenResponse>("/auth/otp/verify", {
    method: "POST",
    auth: false,
    body: { phone_e164, code },
  });

// --- recommendation and chat -----------------------------------------------
// Added with the RAG modules. The types are transcribed from
// `services/api/app/modules/recommendation/schemas.py` and
// `.../chat/schemas.py`, same rule as everything above.

export interface NextExercise {
  /** `<kind>:<skill code>` — the same activity-code shape `progress` produces. */
  activity_code: string;
  skill_id: string;
  skill_code: string;
  label_ar: string;
  /** lapsed | due | new | confidence — why the engine offered it at all. */
  kind: string;
  reason_ar: string;
  /**
   * Which path produced this. The caregiver never sees it; the console does,
   * and "was this the model or the engine" is the first question anyone
   * reviewing a bad recommendation asks.
   */
  source: "ai" | "deterministic_fallback";
  plan: string[];
  grounded_in: string[];
}

export const getNextExercise = (childId: string) =>
  apiFetchOrNull<NextExercise>(`/children/${childId}/recommendation`);

export type TurnOutcome = "ok" | "escalated" | "blocked" | "fallback";

export interface ChatMessage {
  role: "user" | "assistant";
  text_ar: string;
  at: string;
  outcome: TurnOutcome;
}

export const getChatHistory = (childId: string, surface: "caregiver" | "child" = "caregiver") =>
  apiFetchOrNull<{ surface: string; messages: ChatMessage[] }>(
    `/chat/children/${childId}/history?surface=${surface}`,
  );

export interface SpeechCapability {
  supported: boolean;
  provider: string;
  /** What the client should do instead when `supported` is false. */
  client_fallback: string;
  detail_ar: string;
}

export const getSpeechCapabilities = () =>
  apiFetchOrNull<{ tts: SpeechCapability; stt: SpeechCapability }>("/chat/speech/capabilities");

/** Writes. Server actions want the throwing version. */
export const askCoach = (childId: string, message: string) =>
  apiFetch<{ text_ar: string; outcome: TurnOutcome; grounded_in: string[] }>(
    `/chat/children/${childId}/ask`,
    { method: "POST", body: { message } },
  );

export const sayToNour = (childId: string, heard: string) =>
  apiFetch<{
    text_ar: string;
    outcome: TurnOutcome;
    phrase_id: string | null;
    audio_key: string | null;
  }>(`/chat/children/${childId}/say`, { method: "POST", body: { heard } });

export const reindexMemory = (childId: string) =>
  apiFetch<{ indexed: number }>(`/children/${childId}/recommendation/reindex`, {
    method: "POST",
  });

// --- the tutor loop's caregiver-facing reads --------------------------------
// Transcribed from `services/api/app/modules/tutor/schemas.py` and
// `.../starting/schemas.py`, same rule as everything above.

export interface RewardsSummary {
  child_id: string;
  stars: number;
  achievements: { code: string; label_ar: string; awarded_at: string }[];
}

export const getRewards = (childId: string) =>
  apiFetchOrNull<RewardsSummary>(`/children/${childId}/rewards`);

export interface StartingSummary {
  assessment_id: string;
  child_id: string;
  status: string;
  completed_at: string | null;
  /** area code -> band index 0..3, exactly as derived. */
  area_levels: Record<string, number>;
  supports: {
    effective_support?: string;
    effective_modality?: string;
    comfortable_minutes?: number;
    demonstration_helps?: boolean;
    follows_spoken?: boolean;
    comfortable_speaking?: boolean;
    unmapped_areas?: string[];
  };
}

export const getStartingAssessment = (childId: string) =>
  apiFetchOrNull<StartingSummary>(`/children/${childId}/starting-assessment`);

export interface SessionFacts {
  activities_completed: number;
  correct: number;
  incorrect: number;
  no_response: number;
  independent_responses: number;
  supported_responses: number;
  skills_practised: string[];
  skill_labels_ar: string[];
  activity_types: string[];
  mastery_changes: {
    skill_code: string;
    skill_label_ar: string;
    from_state: string;
    to_state: string;
  }[];
  stars_earned: number;
  achievements_unlocked: string[];
  duration_minutes: number;
  best_streak: number;
  went_well: string[];
  needs_practice: string[];
  median_latency_ms: number | null;
}

export interface CaregiverReport {
  session_id: string;
  child_id: string;
  created_at: string;
  facts: SessionFacts;
  narrative_ar: string;
  /** 'template' or 'ai'. A caregiver is never told a template was written. */
  narrative_source: string;
}

export const getSessionReport = (sessionId: string) =>
  apiFetchOrNull<CaregiverReport>(`/tutor/sessions/${sessionId}/report`);

export interface InspectorDecision {
  decision_id: string;
  ordinal: number;
  created_at: string;
  model_name: string;
  used_ai: boolean;
  skill: string | null;
  difficulty: number | null;
  strategy: string | null;
  modality: string | null;
  support_level: string | null;
  activity_type: string | null;
  repeat: boolean | null;
  reason_codes: string[];
  guardrail_actions: string[];
  changed_by_guardrails: boolean;
  p_known_at_decision: number | null;
  recent_results: string[];
  modality_accuracy: Record<string, number>;
  resulting_activity: string | null;
}

export interface Inspector {
  session_id: string;
  child_id: string;
  plan_source: string;
  decisions: InspectorDecision[];
  activities: {
    ordinal: number;
    activity_type: string;
    skill_code: string;
    skill_label_ar: string;
    difficulty: number;
    strategy: string;
    support_level: string;
    state: string;
  }[];
  attempts: {
    skill_code: string;
    result: string;
    prompt_level: string;
    latency_ms: number | null;
  }[];
}

export const getInspector = (sessionId: string) =>
  apiFetchOrNull<Inspector>(`/tutor/sessions/${sessionId}/inspector`);
