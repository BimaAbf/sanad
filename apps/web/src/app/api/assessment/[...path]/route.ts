import { NextResponse } from "next/server";

import { ApiError, apiFetch } from "@/lib/api";
import { getActiveChildId } from "@/lib/session";

/**
 * The assessment runner's hop to the API.
 *
 * Same reason as `api/play/session`: the runner is a client component — it has
 * to be, because it is three big buttons and a text box — so it cannot call
 * `apiFetch`, which reads the access token from an httpOnly cookie. The browser
 * posts here with no credentials of its own and the token is attached
 * server-side.
 *
 * `POST /api/assessment/start` fills in the child from the caregiver's cookie;
 * the two `{id}` routes are passed through. The allow-list is what keeps this
 * from being a general proxy to every POST route on the API, authenticated with
 * the caregiver's own token.
 */

const ANSWER = /^[0-9a-f-]{36}\/answers$/i;
const FINALISE = /^[0-9a-f-]{36}\/finalise$/i;

export async function POST(
  request: Request,
  context: { params: Promise<{ path: string[] }> },
): Promise<NextResponse> {
  const { path } = await context.params;
  const suffix = path.join("/");

  let body: Record<string, unknown> = {};
  try {
    body = (await request.json()) as Record<string, unknown>;
  } catch {
    body = {};
  }

  let target: string;
  if (suffix === "start") {
    const childId = await getActiveChildId();
    if (!childId) {
      return NextResponse.json({ code: "no_active_child" }, { status: 409 });
    }
    target = "/assessments";
    body = { child_id: childId };
  } else if (ANSWER.test(suffix) || FINALISE.test(suffix)) {
    target = `/assessments/${suffix}`;
  } else {
    return NextResponse.json({ code: "not_found" }, { status: 404 });
  }

  try {
    return NextResponse.json(
      await apiFetch<unknown>(target, { method: "POST", body }),
    );
  } catch (error) {
    if (error instanceof ApiError) {
      // `status: 0` is `apiFetch`'s "the request never arrived"; 0 is not an
      // HTTP status and the client switches on the number.
      const status = error.status === 0 ? 503 : error.status;
      return NextResponse.json({ code: error.code, message_ar: error.messageAr }, { status });
    }
    return NextResponse.json({ code: "network_unavailable" }, { status: 503 });
  }
}
