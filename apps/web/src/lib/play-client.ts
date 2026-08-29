/**
 * The client half of the play session: starting one, and the outbox's sender.
 *
 * `Outbox` was built with a `Poster` port and then constructed with
 * `async () => ({ ok: true })` — a sender that acknowledged every attempt
 * without sending it. Every tap a child made was written to memory, marked
 * delivered, and pruned five minutes later. This is the real one.
 *
 * Everything here goes through the same-origin `/api/play` proxy, never the API
 * directly: the access token is in an httpOnly cookie that client script cannot
 * read, and that is the point of it being httpOnly.
 */

import type { Poster } from "@/lib/outbox";

export interface PlayChoice {
  skill_id: string;
  code: string;
  label_ar: string;
  alt_ar: string;
  correct: boolean;
}

export interface PlayActivity {
  activity_code: string;
  skill_id: string;
  skill_code: string;
  instruction_ar: string;
  choices: PlayChoice[];
}

export interface PlaySession {
  session_id: string;
  child_id: string;
  started_at: string;
  plan_source: string;
  wait_time_ms: number;
  max_choices: number;
  calm_mode: boolean;
  activities: PlayActivity[];
}

/** Where the outbox posts an attempt for a given session. */
export const attemptsEndpoint = (sessionId: string): string =>
  `/play/sessions/${sessionId}/attempts`;

/**
 * Start a session and get the whole plan.
 *
 * Returns null rather than throwing on any failure. There is no failure state
 * in the child app (docs/04e §C13) — not for the network either — so the caller
 * falls back to the bundled plan and the session still runs.
 */
export async function startSession(minutes?: number): Promise<PlaySession | null> {
  try {
    const response = await fetch("/api/play/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(minutes === undefined ? {} : { minutes }),
    });
    if (!response.ok) return null;
    return (await response.json()) as PlaySession;
  } catch {
    return null;
  }
}

/**
 * The outbox's sender. Maps an API path to the proxy and reports three
 * outcomes, because the outbox distinguishes them:
 *
 * * `ok` — stored.
 * * `duplicate` — the server already had this key, which is a SUCCESS. The
 *   outbox stops retrying; treating it as a failure would retry forever.
 * * neither — still pending, try again on the next `online` event.
 *
 * A 4xx that is not a duplicate is also treated as delivered. It will never
 * succeed on retry, and a permanently stuck record blocks every attempt behind
 * it in the queue.
 */
export const playPoster: Poster = async (endpoint, body, idempotencyKey) => {
  let response: Response;
  try {
    response = await fetch(`/api${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
      body: JSON.stringify(body),
    });
  } catch {
    return { ok: false };
  }

  if (response.ok) {
    // The API answers `{accepted, duplicates}`. `accepted: 0` means the server
    // already had it — the outbox drain after a dropped connection.
    try {
      const result = (await response.json()) as { accepted?: number; duplicates?: number };
      return { ok: true, duplicate: (result.duplicates ?? 0) > 0 && (result.accepted ?? 0) === 0 };
    } catch {
      return { ok: true };
    }
  }
  if (response.status >= 400 && response.status < 500 && response.status !== 429) {
    return { ok: false, duplicate: true };
  }
  return { ok: false };
};

/** Close the session so it reaches the caregiver's dashboard. Never throws. */
export async function endSession(
  sessionId: string,
  { minutes, reason = "completed" }: { minutes: number; reason?: string },
): Promise<void> {
  try {
    await fetch(`/api/play/sessions/${sessionId}/end`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason, minutes }),
    });
  } catch {
    // A session that ends without reaching the server is a dashboard that is
    // one session out of date. It is not something to tell a child about.
  }
}
