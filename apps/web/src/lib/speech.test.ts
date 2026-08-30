import { afterEach, describe, expect, it, vi } from "vitest";

import {
  SPEECH_LOCALE,
  arabicVoices,
  listenOnce,
  speak,
  speechSupport,
  stopSpeaking,
} from "@/lib/speech";

/**
 * Feature detection is the whole design of `speech.ts`, so these tests are
 * mostly about what happens when a capability is ABSENT — Firefox has no
 * `SpeechRecognition` at all, and a component that assumed otherwise would
 * render a microphone that does nothing when a caregiver taps it.
 *
 * `globalThis` is shaped per test rather than mocked at module scope, because
 * the functions read the browser globals at call time on purpose: `getVoices()`
 * is empty on its first call in Chrome and the answer legitimately changes.
 */

interface FakeUtterance {
  text: string;
  lang: string;
  rate: number;
  voice: unknown;
  onend: (() => void) | null;
}

/**
 * `vitest.config.mts` runs this suite in the `node` environment, where there is
 * no `window` at all. That is not an obstacle to work around -- it is the exact
 * condition `speech.ts` guards for on every entry point, because these
 * functions are imported by modules that render on the server. So each test
 * builds the window it wants: absent, half-present, or fully capable.
 */
function installWindow(parts: Record<string, unknown> = {}) {
  vi.stubGlobal("window", parts);
  return parts;
}

function installSynthesis(voices: { lang: string; name: string }[] = []) {
  const spoken: FakeUtterance[] = [];
  const cancel = vi.fn();
  installWindow({
    speechSynthesis: {
      getVoices: () => voices,
      speak: (utterance: FakeUtterance) => spoken.push(utterance),
      cancel,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    },
  });
  vi.stubGlobal(
    "SpeechSynthesisUtterance",
    class {
      text: string;
      lang = "";
      rate = 1;
      voice: unknown = null;
      onend: (() => void) | null = null;
      constructor(text: string) {
        this.text = text;
      }
    },
  );
  return { spoken, cancel };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("speechSupport", () => {
  it("reports nothing available when the browser has neither", () => {
    expect(speechSupport()).toEqual({
      synthesis: false,
      recognition: false,
      arabicVoice: false,
    });
  });

  it("separates 'TTS exists' from 'an Arabic voice is installed'", () => {
    // The distinction matters: synthesis with no ar-* voice reads Arabic text
    // in a Latin voice, which is worse than not offering the button.
    installSynthesis([{ lang: "en-US", name: "Daniel" }]);
    const support = speechSupport();
    expect(support.synthesis).toBe(true);
    expect(support.arabicVoice).toBe(false);

    vi.unstubAllGlobals();
    installSynthesis([{ lang: "ar-EG", name: "Salma" }]);
    expect(speechSupport().arabicVoice).toBe(true);
  });

  it("detects the webkit-prefixed recogniser Safari ships", () => {
    installWindow({ webkitSpeechRecognition: class {} });
    expect(speechSupport().recognition).toBe(true);
  });
});

describe("arabicVoices", () => {
  it("keeps every ar-* variant, not only ar-EG", () => {
    installSynthesis([
      { lang: "ar-SA", name: "Maged" },
      { lang: "ar-EG", name: "Salma" },
      { lang: "fr-FR", name: "Amelie" },
    ]);
    expect(arabicVoices().map((voice) => voice.lang)).toEqual(["ar-SA", "ar-EG"]);
  });

  it("is empty rather than throwing when there is no synthesis at all", () => {
    expect(arabicVoices()).toEqual([]);
  });
});

describe("speak", () => {
  it("returns false instead of throwing when the browser cannot speak", () => {
    expect(speak("أهلاً")).toBe(false);
  });

  it("refuses empty text", () => {
    installSynthesis([{ lang: "ar-EG", name: "Salma" }]);
    expect(speak("   ")).toBe(false);
  });

  it("cancels before speaking", () => {
    // Two overlapping utterances is the most common Web Speech bug, and it is
    // unintelligible rather than merely untidy.
    const { cancel, spoken } = installSynthesis([{ lang: "ar-EG", name: "Salma" }]);
    expect(speak("أهلاً")).toBe(true);
    expect(cancel).toHaveBeenCalled();
    expect(spoken).toHaveLength(1);
  });

  it("speaks Egyptian Arabic at the profile's rate", () => {
    const { spoken } = installSynthesis([{ lang: "ar-EG", name: "Salma" }]);
    speak("أهلاً", { ratePct: 85 });
    expect(spoken[0]?.lang).toBe(SPEECH_LOCALE);
    expect(spoken[0]?.rate).toBeCloseTo(0.85);
  });

  it("clamps an absurd rate rather than passing it through", () => {
    const { spoken } = installSynthesis([{ lang: "ar-EG", name: "Salma" }]);
    speak("أهلاً", { ratePct: 900 });
    expect(spoken[0]?.rate).toBe(2);
    speak("أهلاً", { ratePct: 1 });
    expect(spoken[1]?.rate).toBe(0.5);
  });

  it("picks an Arabic voice when one exists", () => {
    const { spoken } = installSynthesis([
      { lang: "en-US", name: "Daniel" },
      { lang: "ar-EG", name: "Salma" },
    ]);
    speak("أهلاً");
    expect((spoken[0]?.voice as { name: string } | null)?.name).toBe("Salma");
  });
});

describe("stopSpeaking", () => {
  it("is safe to call when there is no synthesis", () => {
    expect(() => stopSpeaking()).not.toThrow();
  });
});

/**
 * A recogniser whose instance the test can reach, installed on the window the
 * way a browser installs it. The unprefixed name is Chrome's; the prefixed one
 * has its own test above.
 */
function installRecognition(options: { failOnStart?: boolean } = {}) {
  const captured: { instance: Record<string, unknown> | null } = { instance: null };
  class FakeRecognition {
    lang = "";
    continuous = true;
    interimResults = true;
    maxAlternatives = 0;
    onresult: ((event: unknown) => void) | null = null;
    onerror: ((event: { error: string }) => void) | null = null;
    onend: (() => void) | null = null;
    stop = vi.fn();
    abort = vi.fn();
    start = vi.fn(() => {
      if (options.failOnStart) throw new Error("InvalidStateError");
    });
    constructor() {
      captured.instance = this as unknown as Record<string, unknown>;
    }
  }
  installWindow({ SpeechRecognition: FakeRecognition });
  return captured;
}

describe("listenOnce", () => {
  it("returns null when the browser has no recogniser", () => {
    // Firefox. The caller renders no microphone at all rather than a dead one.
    installWindow();
    expect(listenOnce({ onResult: () => undefined })).toBeNull();
  });

  it("asks for one finished utterance, not a stream of partials", () => {
    // Every consumer would otherwise re-implement the same debounce.
    const captured = installRecognition();
    listenOnce({ onResult: () => undefined });
    expect(captured.instance?.continuous).toBe(false);
    expect(captured.instance?.interimResults).toBe(false);
    expect(captured.instance?.lang).toBe(SPEECH_LOCALE);
  });

  it("hands back the trimmed transcript and a way to cancel", () => {
    const captured = installRecognition();
    const heard: string[] = [];
    const cancel = listenOnce({ onResult: (text) => heard.push(text) });
    expect(cancel).not.toBeNull();

    (captured.instance?.onresult as (event: unknown) => void)({
      results: [[{ transcript: " أحمر " }]],
    });
    expect(heard).toEqual(["أحمر"]);

    cancel?.();
    expect(captured.instance?.abort).toHaveBeenCalled();
  });

  it("passes the browser's confidence through, and zero when there is none", () => {
    // The server distinguishes "the recogniser was unsure" from "the recogniser
    // does not estimate confidence". Substituting a number here would collapse
    // the two and make every attempt on a browser without the field read as
    // uncertain.
    const captured = installRecognition();
    const heard: [string, number][] = [];
    listenOnce({ onResult: (text, confidence) => heard.push([text, confidence]) });

    (captured.instance?.onresult as (event: unknown) => void)({
      results: [[{ transcript: "أحمر", confidence: 0.87 }]],
    });
    (captured.instance?.onresult as (event: unknown) => void)({
      results: [[{ transcript: "أزرق" }]],
    });
    expect(heard).toEqual([
      ["أحمر", 0.87],
      ["أزرق", 0],
    ]);
  });

  it("ignores a blank transcript", () => {
    const captured = installRecognition();
    const heard: string[] = [];
    listenOnce({ onResult: (text) => heard.push(text) });
    (captured.instance?.onresult as (event: unknown) => void)({
      results: [[{ transcript: "   " }]],
    });
    expect(heard).toEqual([]);
  });

  it("reports a start() that throws instead of taking the page down", () => {
    // Chrome throws if start() is called while already listening. That is a
    // caller bug, not a browser failure.
    installRecognition({ failOnStart: true });
    const errors: string[] = [];
    const cancel = listenOnce({
      onResult: () => undefined,
      onError: (reason) => errors.push(reason),
    });
    expect(cancel).toBeNull();
    expect(errors).toHaveLength(1);
  });

  it("forwards a recogniser error and the end of the utterance", () => {
    const captured = installRecognition();
    const errors: string[] = [];
    let ended = false;
    listenOnce({
      onResult: () => undefined,
      onError: (reason) => errors.push(reason),
      onEnd: () => {
        ended = true;
      },
    });
    (captured.instance?.onerror as (event: { error: string }) => void)({ error: "no-speech" });
    (captured.instance?.onend as () => void)();
    expect(errors).toEqual(["no-speech"]);
    expect(ended).toBe(true);
  });
});
