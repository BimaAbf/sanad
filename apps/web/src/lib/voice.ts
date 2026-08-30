/**
 * Nour's voice.
 *
 * The product's voice is Azure ar-EG neural TTS, pre-generated per activity and
 * delivered as `instruction_audio` URLs in the session manifest (docs/04d).
 * This module is the layer in front of it, and it adds exactly two things to
 * `lib/speech.ts`, which already owns everything about the browser's own
 * synthesis:
 *
 * 1. **A manifest clip is preferred whenever there is one.** One voice, one
 *    rate, identical repetition (docs/04e §C13) is only achievable with
 *    pre-generated audio; a device voice varies by phone and by OS version.
 * 2. **A missing clip must not silence Nour.** docs/01 P4 — every AI failure
 *    has a silent deterministic fallback — and P5 — the child is never blocked.
 *    A 404 on one activity's audio makes that activity speak in the device
 *    voice, not in no voice.
 *
 * Which of the two spoke is recorded in `lastSource`, because a session running
 * mostly on device voices is a content-pipeline failure and should be visible
 * as one rather than merely sound slightly different.
 *
 * Nothing here throws. A browser with no speech synthesis at all gets silence,
 * and the activity still has its written instruction, its picture and its
 * prompt ladder — the other modalities docs/06 §4 requires precisely so that
 * audio is never the only way through.
 */

import { speak, stopSpeaking } from "@/lib/speech";

export type VoiceSource = "manifest" | "device" | "none";

export interface Voice {
  /** Say `text`, preferring `audioUrl` when the manifest supplied one. */
  speak(text: string, audioUrl?: string | undefined): Promise<void>;
  stop(): void;
  readonly lastSource: VoiceSource;
}

export interface VoiceOptions {
  /** `child.audio_rate_pct` — 85 by default. Slower than default on purpose. */
  ratePct?: number;
  /** Calm mode silences sound effects. It never silences the instruction. */
  enabled?: boolean;
}

const SILENT: Voice = {
  async speak() {},
  stop() {},
  lastSource: "none",
};

export function createVoice({ ratePct = 85, enabled = true }: VoiceOptions = {}): Voice {
  if (!enabled || typeof window === "undefined") return SILENT;

  let element: HTMLAudioElement | null = null;
  let source: VoiceSource = "none";

  const device = (text: string) =>
    new Promise<void>((resolve) => {
      const started = speak(text, { ratePct, onEnd: () => resolve() });
      source = started ? "device" : "none";
      // `speak` returns false when this browser has no synthesis at all. There
      // is no `onend` coming in that case, so resolve rather than hang — a
      // caller awaiting a promise that never settles would leave Nour stuck in
      // her speaking state for the rest of the session.
      if (!started) resolve();
    });

  return {
    get lastSource() {
      return source;
    },
    stop() {
      stopSpeaking();
      element?.pause();
      element = null;
    },
    async speak(text, audioUrl) {
      this.stop();
      if (audioUrl) {
        try {
          element = new Audio(audioUrl);
          element.preload = "auto";
          source = "manifest";
          await element.play();
          return;
        } catch {
          // Fall through to the device voice. A 404 on one clip must not be the
          // difference between a session that speaks and one that does not.
        }
      }
      await device(text);
    },
  };
}
