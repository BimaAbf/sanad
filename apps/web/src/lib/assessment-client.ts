/**
 * The assessment runner's client.
 *
 * The runner has always held its question in `useState(PLACEHOLDER_QUESTION)`
 * and thrown every answer away with `void verdict`. This is the other half:
 * three calls, all through the same-origin `/api/assessment` proxy, because the
 * access token is in an httpOnly cookie that client script cannot read.
 *
 * Unlike the child app, a failure here is NOT hidden. A caregiver answering
 * fifty questions about their child must not be told the assessment is
 * progressing when nothing is being saved — so these return null and the runner
 * says so once, rather than silently carrying on.
 */

/** Transcribed from `assessment/schemas.py::ItemOut`. */
export interface AssessmentItem {
  item_id: string;
  domain: string;
  band: number;
  ordinal: number;
  prompt_ar: string;
  prompt_ar_msa: string;
  example_ar: string;
}

/** Transcribed from `assessment/schemas.py::AssessmentState`. */
export interface AssessmentState {
  assessment_id: string;
  status: string;
  bank_version: string;
  child_months: number;
  answered: number;
  remaining_estimate: number;
  complete: boolean;
  next_items: AssessmentItem[];
  /** Non-empty while the item bank is unreviewed placeholder content. */
  bank_watermark: string;
}

export interface AssessmentScored {
  assessment_id: string;
  status: string;
  completed_at: string;
  domain_da: Record<string, number>;
  skills_mastered: number;
}

/** The five `response_verdict` values the API accepts. */
export type ApiVerdict = "yes" | "emerging" | "no" | "not_applicable" | "skipped";

async function post<T>(path: string, body: unknown): Promise<T | null> {
  try {
    const response = await fetch(`/api/assessment/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) return null;
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

/** Start, or resume the one already open for this child. */
export const startAssessment = (): Promise<AssessmentState | null> =>
  post<AssessmentState>("start", {});

/**
 * Record one answer and get the next questions.
 *
 * The idempotency key is derived, not random: a retry after a timeout must
 * carry the SAME key, and a random one would make the retry a second answer.
 *
 * The VERDICT is part of the key, and that is the load-bearing detail. Keyed on
 * the item alone, a correction — the whole point of the confirmable chip — would
 * arrive with a key the server already had and be swallowed as a duplicate, so
 * the caregiver's correction would silently not happen. Including the verdict
 * keeps a retry idempotent and lets a genuine change through as the correction
 * it is.
 */
export const answerItem = (
  assessmentId: string,
  itemId: string,
  verdict: ApiVerdict,
): Promise<AssessmentState | null> =>
  post<AssessmentState>(`${assessmentId}/answers`, {
    item_id: itemId,
    verdict,
    source: "caregiver_tap",
    idempotency_key: `${assessmentId}:${itemId}:${verdict}`,
  });

/** Score every domain and close. Safe to call twice. */
export const finaliseAssessment = (assessmentId: string): Promise<AssessmentScored | null> =>
  post<AssessmentScored>(`${assessmentId}/finalise`, {});
