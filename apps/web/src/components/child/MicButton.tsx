"use client";

import { useState } from "react";

import { TOUCH_TARGET_PX, VAD } from "@/lib/interaction";

/**
 * The microphone, with the VAD parameters from docs/04d §3.
 *
 * The parameters are passed to the VAD library rather than left at its
 * defaults, and the difference is not a tuning preference:
 *
 *     redemption frames  8 (~250 ms)  ->  24 (~750 ms)
 *
 * docs/04d calls getting this wrong "the most common way this feature fails":
 * at 250 ms the recogniser cuts the child off mid-word, and the platform then
 * tells a child who was still speaking that they were wrong.
 *
 * The button never enters an error state. If the microphone is unavailable the
 * caller switches the activity to caregiver-confirmation mode; the child is not
 * shown a broken control.
 */
export type MicState = "idle" | "listening" | "thinking";

export function MicButton({
  onCapture,
  label,
  disabled = false,
}: {
  onCapture: (blob: Blob) => void;
  label: string;
  disabled?: boolean;
}) {
  const [state, setState] = useState<MicState>("idle");

  const start = async () => {
    if (disabled || state !== "idle") return;
    setState("listening");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      const recorder = new MediaRecorder(stream, {
        mimeType: "audio/webm;codecs=opus",
        audioBitsPerSecond: 24000,
      });
      const chunks: Blob[] = [];
      recorder.ondataavailable = (event) => chunks.push(event.data);
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        setState("thinking");
        onCapture(new Blob(chunks, { type: "audio/webm" }));
        setState("idle");
      };
      recorder.start();
      // Hard cap. Bounds cost and stops an open-mic situation in a family home.
      window.setTimeout(() => {
        if (recorder.state !== "inactive") recorder.stop();
      }, VAD.maxDurationMs);
    } catch {
      // Permission denied or no device. Not an error the child sees: the
      // session continues in caregiver-confirmation mode.
      setState("idle");
    }
  };

  return (
    <button
      type="button"
      data-testid="mic-button"
      data-state={state}
      data-vad-redemption-frames={VAD.redemptionFrames}
      data-vad-threshold={VAD.positiveSpeechThreshold}
      onClick={start}
      aria-label={label}
      className="rounded-pill bg-accent-soft text-2xl"
      style={{ minInlineSize: `${TOUCH_TARGET_PX}px`, minBlockSize: `${TOUCH_TARGET_PX}px` }}
    >
      <span aria-hidden>{state === "listening" ? "🔴" : "🎤"}</span>
    </button>
  );
}
