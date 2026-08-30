"use server";

import { redirect } from "next/navigation";

import { setActiveChildId } from "@/lib/session";

/**
 * Choosing which child is playing.
 *
 * A server action rather than a link with a query string, because it writes the
 * httpOnly cookie `/play` reads. A child id in the URL would be a child id in
 * the browser history, in a screenshot, and in whatever the caregiver pastes
 * into a message when asking for help.
 */
export async function selectChildAction(formData: FormData): Promise<void> {
  const childId = String(formData.get("child_id") ?? "");
  if (childId) await setActiveChildId(childId);
  // Outside any try: `redirect()` signals by throwing, and catching it would
  // turn a successful selection into a silent no-op.
  redirect("/play");
}
