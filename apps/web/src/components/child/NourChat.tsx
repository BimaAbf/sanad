"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { sayToNourAction, type NourTurn } from "@/app/(play)/play/actions";
import { TOUCH_TARGET_PX } from "@/lib/interaction";
import { listenOnce, speak, speechSupport, stopSpeaking, whenVoicesReady } from "@/lib/speech";

/**
 * Nour listening, and answering with one of seven reviewed phrases.
 *
 * The constraint that shapes this component is on the server: `chat/domain.py`
 * holds a closed set of phrases, the model's whole job is to pick one, and a
 * guardrail rejects anything else. So there is no streaming, no partial text,
 * no typing indicator — a reply is one short sentence that already existed
 * before the child spoke.
 *
 * Three rules from docs/04e §C13 that are visible in the markup:
 *
 * * **There is no failure state.** A network error, a refused consent and a
 *   recogniser that heard nothing all produce the same gentle phrase. A child
 *   cannot act on any of those distinctions, and showing an error mid-session
 *   is worse than Nour asking them to say it again.
 * * **The caregiver starts it.** The microphone is not armed on mount. A tap is
 *   what performs the gesture the browser requires before it will listen, and
 *   it is also what stops a tablet left face-up on a table from recording a
 *   room.
 * * **Nothing here is required to play.** If the browser has no recogniser the
 *   component renders nothing at all and the session is unaffected. Speaking to
 *   Nour is an addition to the activity, never a step in it.
 */

export interface NourChatProps {
  childId: string;
  /** From the child's profile. 85% is the default for a reason. */
  audioRatePct?: number;
  /** Called so the character can animate while Nour is talking. */
  onSpeakingChange?: (speaking: boolean) => void;
}

export function NourChat({ childId, audioRatePct = 85, onSpeakingChange }: NourChatProps) {
  const [support, setSupport] = useState({
    synthesis: false,
    recognition: false,
    arabicVoice: false,
  });
  const [listening, setListening] = useState(false);
  const [turn, setTurn] = useState<NourTurn | null>(null);
  const cancelListening = useRef<(() => void) | null>(null);

  useEffect(() => {
    setSupport(speechSupport());
    return whenVoicesReady(() => setSupport(speechSupport()));
  }, []);

  useEffect(() => () => stopSpeaking(), []);

  const reply = useCallback(
    async (heard: string) => {
      const answer = await sayToNourAction(childId, heard);
      setTurn(answer);
      // The reply is spoken, not just shown. A child at `preverbal` or
      // `single_words` is the median user of this screen and the text is not
      // the channel that reaches them.
      //
      // The browser voice is a stand-in. `answer.audioKey` names the clip in
      // the pre-rendered corpus, which is what will play once the renderer has
      // run — that is how Nour's voice stays identical between sessions
      // (Assumption C7), and it is why the server sends a key rather than text
      // alone.
      onSpeakingChange?.(true);
      const spoke = speak(answer.textAr, {
        ratePct: audioRatePct,
        onEnd: () => onSpeakingChange?.(false),
      });
      if (!spoke) onSpeakingChange?.(false);
    },
    [childId, audioRatePct, onSpeakingChange],
  );

  const toggle = useCallback(() => {
    if (listening) {
      cancelListening.current?.();
      cancelListening.current = null;
      setListening(false);
      return;
    }
    const cancel = listenOnce({
      onResult: (transcript) => void reply(transcript),
      onEnd: () => setListening(false),
      // A recogniser error is silent. See the component docstring.
      onError: () => setListening(false),
    });
    if (cancel === null) return;
    cancelListening.current = cancel;
    setListening(true);
  }, [listening, reply]);

  // No recogniser, no component. Rendering a dead microphone to a child is a
  // control that teaches them tapping does nothing.
  if (!support.recognition) return null;

  return (
    <div data-testid="nour-chat" className="flex flex-col items-center gap-3">
      <button
        type="button"
        data-testid="nour-listen"
        data-listening={listening}
        onClick={toggle}
        aria-label={listening ? "نور بتسمعك" : "اتكلم مع نور"}
        className="rounded-pill bg-primary-soft text-3xl"
        style={{
          minInlineSize: `${TOUCH_TARGET_PX}px`,
          minBlockSize: `${TOUCH_TARGET_PX}px`,
        }}
      >
        <span aria-hidden>{listening ? "👂" : "💬"}</span>
      </button>

      {turn ? (
        <p
          data-testid="nour-reply"
          data-phrase={turn.phraseId ?? ""}
          className="text-child font-semibold text-ink"
        >
          {turn.textAr}
        </p>
      ) : null}
    </div>
  );
}
