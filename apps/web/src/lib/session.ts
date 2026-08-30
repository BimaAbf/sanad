/**
 * The caregiver's session, held in httpOnly cookies set by server actions.
 *
 * The API also issues its own `sanad_refresh` cookie, scoped to `/auth` on the
 * API origin. This app deliberately does not try to drive that: a refresh
 * round-trip belongs on the API's own origin, and duplicating the rotation
 * logic here is how a refresh-token family ends up revoked by accident. When
 * the access token expires the caregiver signs in again.
 */

import { cookies } from "next/headers";

import { ACCESS_COOKIE, CHILD_COOKIE } from "@/lib/api";

/** Not `secure` on localhost: the dev server is http and the cookie would never be sent. */
const isProduction = process.env.NODE_ENV === "production";

export async function setAccessToken(token: string, expiresIn: number): Promise<void> {
  (await cookies()).set(ACCESS_COOKIE, token, {
    httpOnly: true,
    sameSite: "lax",
    secure: isProduction,
    path: "/",
    maxAge: expiresIn,
  });
}

export async function getAccessToken(): Promise<string | null> {
  return (await cookies()).get(ACCESS_COOKIE)?.value ?? null;
}

export async function isSignedIn(): Promise<boolean> {
  return (await getAccessToken()) !== null;
}

export async function clearSession(): Promise<void> {
  const jar = await cookies();
  jar.delete(ACCESS_COOKIE);
  jar.delete(CHILD_COOKIE);
}

/**
 * Which child the caregiver is currently looking at.
 *
 * A cookie rather than a URL segment for the top-level pages, because the
 * caregiver app is single-child in the overwhelming majority of cases and
 * making every caregiver carry a uuid in the address bar to see today's screen
 * is a worse default than remembering it. The `/child/[id]/*` routes still take
 * it explicitly, which is what makes two children work.
 */
export async function setActiveChildId(childId: string): Promise<void> {
  (await cookies()).set(CHILD_COOKIE, childId, {
    httpOnly: true,
    sameSite: "lax",
    secure: isProduction,
    path: "/",
    maxAge: 60 * 60 * 24 * 365,
  });
}

export async function getActiveChildId(): Promise<string | null> {
  return (await cookies()).get(CHILD_COOKIE)?.value ?? null;
}
