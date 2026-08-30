import { NextResponse } from "next/server";

import { ApiError, apiFetch } from "@/lib/api";

/**
 * The child app's hop to the tutor loop.
 *
 * The play surface is a client component — it has to be, because it is a
 * canvas, a microphone and a clock — so it cannot call `apiFetch`, which reads
 * the access token from an httpOnly cookie. The browser posts here with no
 * credentials of its own and the token is attached server-side. That matters
 * more on this surface than anywhere else in the app: it is the one a child
 * holds, and it is the last place that should have a credential a page script
 * can read.
 *
 * The allow-list below is what keeps this from being an open proxy to every
 * route on the API, authenticated with the caregiver's own token. A path that
 * does not match one of these four shapes is a 404 here, whatever the API
 * would have done with it.
 */

const SESSIONS = "sessions";
const UUID = /^[0-9a-f-]{36}$/i;

/** `sessions` | `sessions/{id}/next` | `sessions/{id}/respond` | `sessions/{id}/end` */
const SESSION_ACTIONS = new Set(["next", "respond", "end"]);

function target(path: string[]): string | null {
  if (path.length === 1 && path[0] === SESSIONS) return "/tutor/sessions";
  if (
    path.length === 3 &&
    path[0] === SESSIONS &&
    UUID.test(path[1] ?? "") &&
    SESSION_ACTIONS.has(path[2] ?? "")
  ) {
    return `/tutor/sessions/${path[1]}/${path[2]}`;
  }
  return null;
}

export async function POST(
  request: Request,
  context: { params: Promise<{ path: string[] }> },
): Promise<NextResponse> {
  const { path } = await context.params;
  const upstream = target(path);
  if (!upstream) {
    return NextResponse.json({ code: "not_found" }, { status: 404 });
  }

  let body: unknown = {};
  try {
    body = await request.json();
  } catch {
    body = {};
  }

  try {
    return NextResponse.json((await apiFetch<unknown>(upstream, { method: "POST", body })) ?? {});
  } catch (error) {
    if (error instanceof ApiError) {
      // `status: 0` is `apiFetch`'s "the request never arrived". Reported as
      // 503 rather than passed through, because 0 is not an HTTP status and the
      // caller switches on the number.
      const status = error.status === 0 ? 503 : error.status;
      return NextResponse.json(
        { code: error.code, message_ar: error.messageAr },
        { status },
      );
    }
    return NextResponse.json({ code: "network_unavailable" }, { status: 503 });
  }
}
