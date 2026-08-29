/**
 * The server-side API client.
 *
 * Every read and write in the caregiver app goes through here, from a server
 * component or a server action — never from the browser. That is the whole
 * point: the access token lives in an httpOnly cookie and is attached to the
 * outgoing request on the server, so it is never handed to a script in the
 * page. A client-side fetch would have to put the token somewhere JavaScript
 * can read, and this is a child health-adjacent product.
 *
 * Two shapes, because the two callers want different things:
 *
 * * `apiFetch` THROWS `ApiError`. Server actions want that — they catch once
 *   and map to an `ActionState` carrying the server's own Arabic message.
 * * `apiFetchOrNull` returns `null`. Server components rendering a page want
 *   that: a signed-out caregiver or a child with no data yet is an empty state,
 *   not an error boundary, and a thrown exception makes those the same screen.
 *
 * The Arabic in an error comes from the server (`errors.py` puts `message_ar`
 * on every ProblemDetail, already in the product's register). Re-writing it
 * here would mean two sets of caregiver-facing Arabic drifting apart, and only
 * one of them reviewed.
 */

import { cookies } from "next/headers";

/** httpOnly, set by the onboarding server actions. See `lib/session.ts`. */
export const ACCESS_COOKIE = "sanad_access";

/** Which child the caregiver is currently looking at. */
export const CHILD_COOKIE = "sanad_child";

/**
 * Read at call time, not at module load. A module-level constant is baked into
 * the server bundle at build time, which makes one image un-deployable to two
 * environments.
 */
export function apiBaseUrl(): string {
  return (
    process.env.SANAD_API_BASE_URL ??
    process.env.NEXT_PUBLIC_API_BASE_URL ??
    "http://localhost:8000"
  );
}

export class ApiError extends Error {
  /** Machine-readable ProblemDetail code — `consent_required`, and so on. */
  readonly code: string;
  readonly status: number;
  /** Server-authored Egyptian Arabic. Safe to render directly. */
  readonly messageAr: string | null;

  constructor(status: number, code: string, messageAr: string | null) {
    super(`${status} ${code}`);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.messageAr = messageAr;
  }
}

export interface ApiFetchOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  /** Set false for the two unauthenticated auth routes. */
  auth?: boolean;
  signal?: AbortSignal;
}

async function authorisation(): Promise<Record<string, string>> {
  const token = (await cookies()).get(ACCESS_COOKIE)?.value;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** Throws `ApiError` on any non-2xx, and on a request that never arrived. */
export async function apiFetch<T>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const { method = "GET", body, auth = true, signal } = options;

  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (auth) Object.assign(headers, await authorisation());

  // Built up rather than declared inline: `exactOptionalPropertyTypes` is on,
  // so an explicit `body: undefined` is a type error rather than an absent key.
  const init: RequestInit = {
    method,
    headers,
    // Never cache a child's clinical record. Next would otherwise cache a GET
    // from a server component, and the second caregiver to load the page would
    // be served the first one's answer.
    cache: "no-store",
  };
  if (body !== undefined) init.body = JSON.stringify(body);
  if (signal !== undefined) init.signal = signal;

  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl()}${path}`, init);
  } catch {
    // Reaching our own API failed. Not the caregiver's fault, and there is no
    // server-authored message to show, so `messageAr` is null and the caller
    // decides what to say.
    throw new ApiError(0, "network_unavailable", null);
  }

  if (response.status === 204) return undefined as T;

  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok) {
    const problem = (payload ?? {}) as { code?: string; message_ar?: string };
    throw new ApiError(
      response.status,
      problem.code ?? "unknown_error",
      problem.message_ar ?? null,
    );
  }
  return payload as T;
}

/**
 * `null` instead of a throw.
 *
 * Every failure collapses to `null` deliberately. A page renders the same empty
 * state whether the caregiver is signed out, the child has no data yet, or the
 * API is down — and distinguishing those on a dashboard would mean three
 * screens where the caregiver needs one. Server actions, which do need the
 * distinction, use `apiFetch`.
 */
export async function apiFetchOrNull<T>(
  path: string,
  options: ApiFetchOptions = {},
): Promise<T | null> {
  try {
    return await apiFetch<T>(path, options);
  } catch {
    return null;
  }
}
