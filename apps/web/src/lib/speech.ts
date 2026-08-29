/**
 * Browser speech — the stand-in until the vendor question is settled.
 *
 * The server answers `supported: false` for both directions today
 * (`services/api/app/modules/chat/speech.py` says why at length), and names a
 * `client_fallback`. This module is that fallback: the Web Speech API, which
 * costs nothing, needs no key, and keeps a caregiver's voice on their own
 * device.
 *
 * **Feature detection is the whole design here.** Firefox ships no
 * `SpeechRecognition` at all, Safari gates it behind a prefix and a permission
 * prompt, and Arabic voice availability for synthesis varies by OS. So nothing
 * in this file assumes anything: `speechSupport()` reports what this browser
 * can actually do, and the components render a microphone button only when the
 * answer is yes. A control that does nothing when tapped is worse than an
 * absent one, especially for a caregiver who will conclude the app is broken.
 *
 * Pure browser API access, no React. Every function is a no-op returning a
 * falsy result on the server, so importing it from a shared module is safe.
 */

/** The prefixed constructor Chrome and Safari expose. */
interface SpeechRecognitionLike extends EventTarget {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
}

interface SpeechRecognitionEventLike {
  results: ArrayLike<ArrayLike<{ transcript: string }>>;
}

type RecognitionConstructor = new () => SpeechRecognitionLike;

interface SpeechWindow extends Window {
  SpeechRecognition?: RecognitionConstructor;
  webkitSpeechRecognition?: RecognitionConstructor;
}

/**
 * Egyptian Arabic. `ar-EG` rather than `ar`: the recogniser's dialect model
 * matters more than almost anything else for this product's vocabulary, and a
 * caregiver saying a colloquial word into an MSA model gets a different word
 * back.
 */
export const SPEECH_LOCALE = "ar-EG";

export interface SpeechSupport {
  synthesis: boolean;
  recognition: boolean;
  /** True when an ar-* voice is actually installed, not merely when TTS exists. */
  arabicVoice: boolean;
}

function recognitionConstructor(): RecognitionConstructor | null {
  if (typeof window === "undefined") return null;
  const scope = window as SpeechWindow;
  return scope.SpeechRecognition ?? scope.webkitSpeechRecognition ?? null;
}

export function speechSupport(): SpeechSupport {
  if (typeof window === "undefined") {
    return { synthesis: false, recognition: false, arabicVoice: false };
  }
  const synthesis = "speechSynthesis" in window;
  return {
    synthesis,
    recognition: recognitionConstructor() !== null,
    arabicVoice: synthesis && arabicVoices().length > 0,
  };
}

/**
 * Voices for Arabic.
 *
 * `getVoices()` is famously empty on first call in Chrome — the list arrives
 * asynchronously — so callers must not treat an empty result as "no Arabic
 * voice, forever". `whenVoicesReady` exists for that.
 */
export function arabicVoices(): SpeechSynthesisVoice[] {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return [];
  return window.speechSynthesis.getVoices().filter((voice) => voice.lang.startsWith("ar"));
}

export function whenVoicesReady(callback: () => void): () => void {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return () => undefined;
  if (window.speechSynthesis.getVoices().length > 0) {
    callback();
    return () => undefined;
  }
  const handler = () => callback();
  window.speechSynthesis.addEventListener("voiceschanged", handler);
  return () => window.speechSynthesis.removeEventListener("voiceschanged", handler);
}

export interface SpeakOptions {
  /**
   * Percent of normal rate. The child profile carries `audio_rate_pct`, default
   * 85, because a slower rate is a comprehension aid for this population — the
   * same reason it is a per-child setting on the server.
   */
  ratePct?: number;
  onEnd?: () => void;
}

/** Speaks `text`. Returns false when this browser cannot. */
export function speak(text: string, options: SpeakOptions = {}): boolean {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return false;
  const trimmed = text.trim();
  if (!trimmed) return false;

  // Cancel first. Two overlapping utterances is the single most common Web
  // Speech bug, and it is unintelligible rather than merely untidy.
  window.speechSynthesis.cancel();

  const utterance = new SpeechSynthesisUtterance(trimmed);
  utterance.lang = SPEECH_LOCALE;
  utterance.rate = Math.min(Math.max((options.ratePct ?? 85) / 100, 0.5), 2);
  const voice = arabicVoices()[0];
  if (voice) utterance.voice = voice;
  if (options.onEnd) utterance.onend = () => options.onEnd?.();
  window.speechSynthesis.speak(utterance);
  return true;
}

export function stopSpeaking(): void {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
  window.speechSynthesis.cancel();
}

export interface ListenHandlers {
  onResult: (transcript: string) => void;
  onError?: (reason: string) => void;
  onEnd?: () => void;
}

/**
 * One utterance, then stop.
 *
 * Returns a cancel function, or null when this browser has no recogniser.
 * `continuous` is false and `interimResults` is false on purpose: the caller
 * wants a finished sentence to send, and a stream of partial transcripts would
 * have every consumer re-implement the same debounce.
 */
export function listenOnce(handlers: ListenHandlers): (() => void) | null {
  const Recognition = recognitionConstructor();
  if (Recognition === null) return null;

  const recognition = new Recognition();
  recognition.lang = SPEECH_LOCALE;
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;

  recognition.onresult = (event) => {
    const first = event.results[0]?.[0]?.transcript ?? "";
    if (first.trim()) handlers.onResult(first.trim());
  };
  recognition.onerror = (event) => handlers.onError?.(event.error);
  recognition.onend = () => handlers.onEnd?.();

  try {
    recognition.start();
  } catch (error) {
    // Chrome throws if start() is called while already listening. That is a
    // caller bug, not a browser failure, and it must not take the page down.
    handlers.onError?.(String(error));
    return null;
  }
  return () => recognition.abort();
}
