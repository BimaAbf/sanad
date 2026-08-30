"use server";

import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import { askCoach, reindexMemory } from "@/lib/queries";

/**
 * The coach's writes.
 *
 * Server actions rather than client fetches, for the same reason onboarding is:
 * the access token lives in an httpOnly cookie and never reaches a script in
 * the page. It also means the question a caregiver types about their child goes
 * browser -> our own server -> our own API, and never sits in a URL, a query
 * string or an access log along the way.
 */

export type CoachOutcome = "ok" | "escalated" | "blocked" | "fallback";

export interface CoachState {
  /** The assistant's answer, or null before the first question. */
  answerAr: string | null;
  /**
   * Which of the four outcomes produced it. The component styles an escalation
   * differently from an answer — collapsing them into "here is some text" is
   * how a refusal gets read as advice.
   */
  outcome: CoachOutcome | null;
  /** What the caregiver asked, so the page can render the exchange. */
  questionAr: string | null;
  /** Server-authored Arabic for a failed request. Never client-invented. */
  errorAr: string | null;
}

export const EMPTY_COACH_STATE: CoachState = {
  answerAr: null,
  outcome: null,
  questionAr: null,
  errorAr: null,
};

/** Shown only when the API answered without a `message_ar`, or never answered. */
const GENERIC_ERROR_AR = "مش قادرين نوصل للخدمة دلوقتي. جرّب تاني بعد شوية.";

export async function askCoachAction(
  _previous: CoachState,
  formData: FormData,
): Promise<CoachState> {
  const childId = String(formData.get("child_id") ?? "");
  const message = String(formData.get("message") ?? "").trim();

  if (!childId || !message) {
    return { ...EMPTY_COACH_STATE, errorAr: "اكتب سؤالك الأول." };
  }

  try {
    const answer = await askCoach(childId, message);
    return {
      answerAr: answer.text_ar,
      outcome: answer.outcome,
      questionAr: message,
      errorAr: null,
    };
  } catch (error) {
    // `consent_required` is the one a caregiver can act on: the assistant is
    // grounded in their child's record, so it is refused outright without
    // `ai_processing` consent rather than answered from nothing. The server's
    // own message names the consent, so it is rendered as-is.
    if (error instanceof ApiError) {
      return {
        ...EMPTY_COACH_STATE,
        questionAr: message,
        errorAr: error.messageAr ?? GENERIC_ERROR_AR,
      };
    }
    return { ...EMPTY_COACH_STATE, questionAr: message, errorAr: GENERIC_ERROR_AR };
  }
}

export interface ReindexState {
  indexed: number | null;
  errorAr: string | null;
}

export const EMPTY_REINDEX_STATE: ReindexState = { indexed: null, errorAr: null };

/**
 * Rebuild this child's retrieval index from their history.
 *
 * Exposed to a caregiver at all because the index is derived data: a session
 * played on another device, or a settings change, is not reflected until the
 * corpus is rebuilt. The alternative — rebuilding on every read — would put a
 * write on the path of a dashboard GET.
 */
export async function reindexAction(
  _previous: ReindexState,
  formData: FormData,
): Promise<ReindexState> {
  const childId = String(formData.get("child_id") ?? "");
  if (!childId) return { indexed: null, errorAr: GENERIC_ERROR_AR };
  try {
    const result = await reindexMemory(childId);
    // The recommendation on this page is derived from the index that just
    // changed, so the cached render of it is now stale.
    revalidatePath(`/child/${childId}/coach`);
    return { indexed: result.indexed, errorAr: null };
  } catch (error) {
    const messageAr = error instanceof ApiError ? error.messageAr : null;
    return { indexed: null, errorAr: messageAr ?? GENERIC_ERROR_AR };
  }
}
