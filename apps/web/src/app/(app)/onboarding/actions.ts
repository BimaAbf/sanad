"use server";

import { redirect } from "next/navigation";

import type { ActionState } from "@/lib/action-state";
import { ApiError, apiFetch } from "@/lib/api";
import { toE164 } from "@/lib/phone";
import { requestOtp, verifyOtp } from "@/lib/queries";
import { setAccessToken, setActiveChildId } from "@/lib/session";

/**
 * The onboarding writes. Server actions, not client fetches.
 *
 * The access token is set into an httpOnly cookie here, on the server, and is
 * never handed to a script in the page. That is the whole reason these are
 * actions: a client-side sign-in would have to put the token somewhere
 * JavaScript can read, and this is a child health-adjacent product.
 */

function failure(error: unknown): ActionState {
  if (error instanceof ApiError) {
    return { ok: false, error: error.messageAr ?? error.message };
  }
  // A network failure reaching our own API is not something to render a stack
  // trace for. It is also not the caregiver's fault, so the copy does not
  // imply they did anything wrong.
  return { ok: false, error: null };
}

export async function requestOtpAction(
  _prev: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const phone = toE164(String(formData.get("phone") ?? ""));
  try {
    await requestOtp(phone);
    return { ok: true, error: null };
  } catch (error) {
    return failure(error);
  }
}

export async function verifyOtpAction(
  _prev: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const phone = toE164(String(formData.get("phone") ?? ""));
  const code = String(formData.get("code") ?? "");
  try {
    const tokens = await verifyOtp(phone, code);
    await setAccessToken(tokens.access_token, tokens.expires_in);
    return { ok: true, error: null };
  } catch (error) {
    return failure(error);
  }
}

interface ChildCreated {
  id: string;
  chronological_months: number;
  corrected_months: number;
}

export async function createChildAction(
  _prev: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const gestational = String(formData.get("gestational_weeks") ?? "").trim();
  const consents = formData
    .getAll("consents")
    .map((value) => ({ key: String(value), granted: true }));

  let created: ChildCreated;
  try {
    created = await apiFetch<ChildCreated>("/children", {
      method: "POST",
      body: {
        display_name: String(formData.get("display_name") ?? ""),
        date_of_birth: String(formData.get("date_of_birth") ?? ""),
        // Sent only when the caregiver answered. An omitted value means "born
        // at term" to the age calculation; a zero would mean something false.
        ...(gestational ? { gestational_weeks: Number(gestational) } : {}),
        consents,
      },
    });
    await setActiveChildId(created.id);
  } catch (error) {
    return failure(error);
  }

  // Outside the try: redirect() signals by throwing, and catching it here would
  // turn a successful sign-up into "something went wrong".
  redirect("/home");
}
