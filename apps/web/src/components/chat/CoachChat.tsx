"use client";

import { useTranslations } from "next-intl";
import { useActionState, useEffect, useRef, useState } from "react";

import {
  EMPTY_COACH_STATE,
  askCoachAction,
  type CoachState,
} from "@/app/(app)/child/[id]/coach/actions";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { CAREGIVER_TOUCH_TARGET_PX } from "@/lib/interaction";
import { listenOnce, speak, speechSupport, stopSpeaking, whenVoicesReady } from "@/lib/speech";

/**
 * The caregiver assistant.
 *
 * Four outcomes, four renderings — and that is the point of the component. The
 * server distinguishes `ok`, `escalated`, `blocked` and `fallback`, and each
 * means something different to the person reading it:
 *
 * * `escalated` — the caregiver said something the keyword screen flagged, and
 *   the model was never called. Styled as a notice, not as an answer, because
 *   it is a signpost to a human being and must not read as advice.
 * * `blocked` — the model answered and a guardrail refused to show it. Said
 *   plainly rather than dressed up as an answer.
 * * `fallback` — nothing was reachable. Distinct from `blocked` so a caregiver
 *   can tell an outage from a refusal and knows whether asking again will help.
 * * `ok` — the answer.
 *
 * Speech is browser-side and feature-detected. The microphone and the speaker
 * render only when this browser actually has them: a control that does nothing
 * when tapped is worse than an absent one, especially for a caregiver who will
 * reasonably conclude the app is broken.
 */

const OUTCOME_TONE: Record<string, string> = {
  ok: "border-border",
  // `attention`, not red. Red reads as failure and nothing here is the
  // caregiver's failure.
  escalated: "border-attention bg-attention/5",
  blocked: "border-attention",
  fallback: "border-border opacity-90",
};

export interface CoachChatProps {
  childId: string;
  /** From the child's profile. A slower rate is a comprehension aid. */
  audioRatePct?: number;
  /**
   * `false` when the server reports a real TTS provider, in which case the
   * browser must not also speak. Read from `/chat/speech/capabilities` rather
   * than assumed, so switching the server on needs no client release.
   */
  useBrowserSpeech?: boolean;
}

export function CoachChat({
  childId,
  audioRatePct = 85,
  useBrowserSpeech = true,
}: CoachChatProps) {
  const t = useTranslations("coach");
  const [state, formAction, pending] = useActionState<CoachState, FormData>(
    askCoachAction,
    EMPTY_COACH_STATE,
  );

  const [support, setSupport] = useState({
    synthesis: false,
    recognition: false,
    arabicVoice: false,
  });
  const [listening, setListening] = useState(false);
  const [draft, setDraft] = useState("");
  const cancelListening = useRef<(() => void) | null>(null);

  // Detected after mount, never during render: the answer differs between the
  // server and the browser, and `getVoices()` is empty on its first call in
  // Chrome, so the check is re-run when the voice list arrives.
  useEffect(() => {
    setSupport(speechSupport());
    return whenVoicesReady(() => setSupport(speechSupport()));
  }, []);

  useEffect(() => () => stopSpeaking(), []);

  const canSpeak = useBrowserSpeech && support.synthesis;
  const canListen = useBrowserSpeech && support.recognition;

  function toggleListening() {
    if (listening) {
      cancelListening.current?.();
      cancelListening.current = null;
      setListening(false);
      return;
    }
    const cancel = listenOnce({
      onResult: (transcript) => setDraft((current) => `${current} ${transcript}`.trim()),
      onEnd: () => setListening(false),
      onError: () => setListening(false),
    });
    if (cancel === null) return;
    cancelListening.current = cancel;
    setListening(true);
  }

  return (
    <div data-testid="coach-chat">
      <form action={formAction} className="space-y-3">
        <input type="hidden" name="child_id" value={childId} />
        <label htmlFor="coach-message" className="block font-semibold text-ink">
          {t("prompt")}
        </label>
        <textarea
          id="coach-message"
          name="message"
          rows={3}
          maxLength={800}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={t("placeholder")}
          className="w-full rounded-md border border-border bg-surface p-3 text-base text-ink"
        />
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={pending || draft.trim().length === 0}>
            {pending ? t("asking") : t("ask")}
          </Button>
          {canListen ? (
            <button
              type="button"
              data-testid="coach-dictate"
              onClick={toggleListening}
              aria-pressed={listening}
              aria-label={listening ? t("stopDictation") : t("dictate")}
              className="rounded-pill border border-border bg-primary-soft px-4 text-xl text-primary"
              style={{
                minBlockSize: `${CAREGIVER_TOUCH_TARGET_PX}px`,
                minInlineSize: `${CAREGIVER_TOUCH_TARGET_PX}px`,
              }}
            >
              <span aria-hidden>{listening ? "⏹" : "🎤"}</span>
            </button>
          ) : null}
        </div>
        {/* Said once, quietly, rather than on every render of the microphone:
            a caregiver on Firefox needs to know why there is no microphone,
            not to be reminded of it every time they type. */}
        {useBrowserSpeech && !support.recognition ? (
          <p className="text-sm text-ink-muted">{t("noDictation")}</p>
        ) : null}
      </form>

      {state.errorAr ? (
        <Card className="mt-5 border-attention" data-testid="coach-error">
          <p className="text-ink">{state.errorAr}</p>
        </Card>
      ) : null}

      {state.answerAr && state.outcome ? (
        <Card
          className={`mt-5 ${OUTCOME_TONE[state.outcome] ?? "border-border"}`}
          data-testid="coach-answer"
          data-outcome={state.outcome}
        >
          {state.questionAr ? (
            <p className="mb-3 text-sm text-ink-muted">{state.questionAr}</p>
          ) : null}
          <p className="whitespace-pre-line text-ink">{state.answerAr}</p>

          {state.outcome === "escalated" ? (
            <p className="mt-3 text-sm font-semibold text-attention">{t("escalatedNote")}</p>
          ) : null}
          {state.outcome === "fallback" ? (
            <p className="mt-3 text-sm text-ink-muted">{t("fallbackNote")}</p>
          ) : null}

          {canSpeak ? (
            <Button
              variant="secondary"
              className="mt-4"
              type="button"
              onClick={() => speak(state.answerAr ?? "", { ratePct: audioRatePct })}
            >
              {t("readAloud")}
            </Button>
          ) : null}
        </Card>
      ) : null}
    </div>
  );
}
