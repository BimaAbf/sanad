/**
 * Getting a session manifest — the wire-up seam.
 *
 * ## The whole integration, in one place
 *
 * ```
 *  child app  ──fetch──▶  /api/play/session  ──apiFetch──▶  POST /play/sessions
 *      │  (this file)      (route handler)                   (C05 Content)
 *      └── local build ◀───────── falls back ────────────────────┘
 * ```
 *
 * The client never talks to the API directly. It talks to its own origin, and
 * the route handler adds the caregiver's bearer token from an httpOnly cookie
 * the browser script cannot read (`lib/api.ts` explains why every read works
 * that way). When the API answers, the child plays the real curriculum the
 * adaptive engine chose. When it does not — not deployed, not configured, the
 * phone is in a lift — the same shape is built from the bundled curriculum and
 * the child plays anyway.
 *
 * That last sentence is the requirement, not a convenience: docs/01 P5, "the
 * child is never blocked", and docs/06 §7, "the child app never starts a
 * session it cannot finish".
 *
 * **To wire the real thing up there is nothing to change here.** Implement
 * `POST /play/sessions` in C05 so it returns the documented manifest, and this
 * function starts returning it. `manifest.local` is how the UI knows which it
 * got; nothing in the games branches on it.
 */

import { buildLocalSession, type LocalSessionOptions, type SessionManifest } from "@/lib/manifest";

export interface LoadSessionRequest extends LocalSessionOptions {
  /** Present once a caregiver has signed in and picked a child. */
  childId?: string | undefined;
}

/** How long to wait for a session before starting the local one instead. */
const TIMEOUT_MS = 4000;

export async function loadSession(request: LoadSessionRequest = {}): Promise<SessionManifest> {
  const local = () => buildLocalSession(request);

  if (typeof fetch === "undefined") return local();

  // An aborted request, not an unbounded one. A child looking at a start screen
  // that never resolves is the failure this timeout exists to prevent — four
  // seconds of nothing is already too long, and there is a perfectly good
  // session sitting in the bundle.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const response = await fetch("/api/play/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal: controller.signal,
    });
    if (!response.ok) return local();
    const manifest = (await response.json()) as SessionManifest;
    // A manifest with no activities is not a session. It is what an empty
    // curriculum or a half-migrated database returns, and playing the bundled
    // one is better than showing a child an empty screen.
    if (!manifest?.activities?.length) return local();
    return manifest;
  } catch {
    return local();
  } finally {
    clearTimeout(timer);
  }
}
