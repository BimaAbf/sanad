import { NextResponse } from "next/server";

import { ApiError, apiFetch } from "@/lib/api";

/**
 * The starting-assessment runner's hop to the API.
 *
 * Same reason as `api/tutor`: the runner is a client component — it is a stack
 * of large buttons that has to respond to a tap without a page load — so it
 * cannot call `apiFetch`, which reads the access token from an httpOnly cookie.
 * The browser posts here with no credentials of its own and the token is
 * attached server-side.
 *
 * The allow-list is what keeps this from being a general proxy to every POST
 * route on the API, authenticated with the caregiver's own token.
 */

const UUID = /^[0-9a-f-]{36}$/i;
const ACTIONS = new Set(["answers", "finalise"]);

function target(path: string[]): string | null {
  if (path.length === 1 && path[0] === "start") return "/starting-assessments";
  if (path.length === 2 && UUID.test(path[0] ?? "") && ACTIONS.has(path[1] ?? "")) {
    return `/starting-assessments/${path[0]}/${path[1]}`;
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
      // `status: 0` is `apiFetch`'s "the request never arrived"; 0 is not an
      // HTTP status and the caller switches on the number.
      const status = error.status === 0 ? 503 : error.status;
      return NextResponse.json(
        { code: error.code, message_ar: error.messageAr },
        { status },
      );
    }
    return NextResponse.json({ code: "network_unavailable" }, { status: 503 });
  }
}
