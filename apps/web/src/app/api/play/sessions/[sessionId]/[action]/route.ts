import { NextResponse } from "next/server";

import { ApiError, apiFetch } from "@/lib/api";

/**
 * Where the outbox drains to, and where a finished session is closed.
 *
 * The outbox stores the API path it will post to (`/play/sessions/{id}/
 * attempts`) and `playPoster` prefixes `/api`, so this handler's path mirrors
 * the API's exactly. Same reason as `../../session/route.ts`: the access token
 * is in an httpOnly cookie and must not enter the page.
 *
 * `action` is constrained to the two the child app performs. Without that this
 * is an open proxy to every POST route on the API, authenticated with the
 * caregiver's own token.
 */

const ACTIONS = new Set(["attempts", "end"]);

export async function POST(
  request: Request,
  context: { params: Promise<{ sessionId: string; action: string }> },
): Promise<NextResponse> {
  const { sessionId, action } = await context.params;
  if (!ACTIONS.has(action)) {
    return NextResponse.json({ detail: "Not a play route." }, { status: 404 });
  }
  // A locally-built session has no server row. Posting its attempts would 404
  // forever and the outbox would retry forever, so it is refused here with the
  // one status the outbox treats as terminal rather than as "try again".
  if (!/^[0-9a-f-]{36}$/i.test(sessionId)) {
    return NextResponse.json({ detail: "Local session." }, { status: 409 });
  }

  let body: unknown = {};
  try {
    body = await request.json();
  } catch {
    body = {};
  }

  try {
    const result = await apiFetch<unknown>(`/play/sessions/${sessionId}/${action}`, {
      method: "POST",
      body,
    });
    return NextResponse.json(result ?? {});
  } catch (error) {
    if (error instanceof ApiError) {
      // `status: 0` is `apiFetch`'s "the request never arrived". Reported as
      // 503 rather than passed through, because 0 is not an HTTP status and the
      // outbox switches on the number.
      const status = error.status === 0 ? 503 : error.status;
      return NextResponse.json({ code: error.code, message_ar: error.messageAr }, { status });
    }
    return NextResponse.json({ code: "network_unavailable" }, { status: 503 });
  }
}
