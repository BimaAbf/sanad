"use server";

import { ApiError } from "@/lib/api";
import { sayToNour } from "@/lib/queries";

/**
 * The child surface's one write.
 *
 * A server action, like every other write in this app, so the access token
 * stays in an httpOnly cookie. It matters more here than anywhere else: the
 * play surface is the one a child holds, and it is the last place that should
 * have a credential readable from the page.
 *
 * The action takes TEXT, never audio. What the child said is transcribed by the
 * browser's own recogniser and nothing leaves the device but the words —
 * which is also why this path needs none of the `voice_asr` consent machinery
 * that `voice/service.py` enforces for uploaded audio.
 */

export interface NourTurn {
  /** One of the seven reviewed phrases. Never generated text. */
  textAr: string;
  phraseId: string | null;
  /** Key into the pre-rendered corpus, so Nour keeps one voice. */
  audioKey: string | null;
  ok: boolean;
}

/**
 * The reply used when the request itself failed.
 *
 * It is the same sentence as the server's own fallback phrase, deliberately.
 * A child must not be able to tell a network failure from Nour mishearing them
 * — there is no failure state on this surface (docs/04e §C13), and "something
 * went wrong" is one.
 */
const OFFLINE_TURN: NourTurn = {
  textAr: "مش سامعك كويس. قولها تاني؟",
  phraseId: "not_understood",
  audioKey: "nour/not_understood.opus",
  ok: false,
};

export async function sayToNourAction(childId: string, heard: string): Promise<NourTurn> {
  const text = heard.trim();
  if (!childId || !text) return OFFLINE_TURN;
  try {
    const reply = await sayToNour(childId, text);
    return {
      textAr: reply.text_ar,
      phraseId: reply.phrase_id,
      audioKey: reply.audio_key,
      ok: true,
    };
  } catch (error) {
    // Even a consent refusal lands here as the neutral phrase. A child cannot
    // act on "your caregiver has not granted ai_processing", and telling them
    // so mid-session would be worse than Nour asking them to say it again.
    if (error instanceof ApiError) return OFFLINE_TURN;
    return OFFLINE_TURN;
  }
}
