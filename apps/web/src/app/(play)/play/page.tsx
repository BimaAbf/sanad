"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";

import { CaregiverOverrideButton } from "@/components/child/CaregiverOverrideButton";
import { ChoiceCard } from "@/components/child/ChoiceCard";
import { MicButton } from "@/components/child/MicButton";
import { NourCharacter, type NourState } from "@/components/child/NourCharacter";
import { SessionDots } from "@/components/child/SessionDots";
import {
  DEFAULT_PROFILE,
  TOUCH_TARGET_PX,
  interActivityPauseMs,
  type AccessibilityProfile,
} from "@/lib/interaction";
import { MemoryOutboxStorage, Outbox, attemptKey } from "@/lib/outbox";
import { rungAt, type Rung } from "@/lib/prompt-ladder";

/**
 * The child's play screen.
 *
 * Everything here follows from one sentence in docs/04e §C13: **there is no
 * failure state**. That is why:
 *
 * * there is no visible timer — the prompt ladder is on a clock the child
 *   cannot see, so waiting is never running out of time;
 * * there is no disabled choice and no "wrong" styling — nothing a child can
 *   tap is an error;
 * * every attempt is written to the outbox before it is posted — a dropped
 *   connection is not something a child should ever find out about;
 * * the caregiver override sits beside every expressive activity permanently,
 *   rather than appearing after two failed tries, because appearing after two
 *   failed tries would mean there had been two failures.
 *
 * The session is fully preloaded before the first prompt (`ready`), so a
 * network drop after that point changes nothing on screen.
 */

interface Choice {
  skillId: string;
  imageUrl: string;
  altAr: string;
  labelAr: string;
  correct: boolean;
}

interface Activity {
  id: string;
  skillId: string;
  instructionAr: string;
  choices: Choice[];
}

// PLACEHOLDER manifest so the shell renders before the API is wired. The real
// one comes from POST /play/sessions and is preloaded into the Cache API.
const PLACEHOLDER_ACTIVITIES: Activity[] = [
  {
    id: "a1",
    skillId: "color_red",
    instructionAr: "وريني الأحمر",
    choices: [
      { skillId: "color_red", imageUrl: "/placeholder/red.svg", altAr: "مربع أحمر", labelAr: "أحمر", correct: true },
      { skillId: "hh_chair", imageUrl: "/placeholder/chair.svg", altAr: "كرسي", labelAr: "كرسي", correct: false },
    ],
  },
];

export default function PlayPage() {
  const t = useTranslations("play");
  const profile: AccessibilityProfile = DEFAULT_PROFILE;

  const [started, setStarted] = useState(false);
  const [index, setIndex] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [nour, setNour] = useState<NourState>("idle");
  const outbox = useRef(new Outbox(new MemoryOutboxStorage(), async () => ({ ok: true })));

  const activity = PLACEHOLDER_ACTIVITIES[index];
  const rung: Rung = rungAt(elapsed, profile.waitTimeMs).rung;

  // The ladder clock. Started only after the caregiver's tap, so a screen left
  // open on a table never advances a ladder for a child who is not there.
  useEffect(() => {
    if (!started) return undefined;
    const timer = window.setInterval(() => setElapsed((value) => value + 250), 250);
    return () => window.clearInterval(timer);
  }, [started, index]);

  // Wake lock: an 8-second wait must not be interrupted by the screen dimming.
  useEffect(() => {
    if (!started) return;
    const nav = navigator as Navigator & {
      wakeLock?: { request: (type: "screen") => Promise<{ release: () => void }> };
    };
    let sentinel: { release: () => void } | null = null;
    nav.wakeLock
      ?.request("screen")
      .then((lock) => {
        sentinel = lock;
      })
      // A refused wake lock is not an error the session should stop for.
      .catch(() => undefined);
    return () => sentinel?.release();
  }, [started]);

  const advance = useCallback(() => {
    setNour("celebrating");
    // 800ms of calm between activities (1200ms in calm mode). Processing time,
    // not a transition.
    window.setTimeout(() => {
      setNour("idle");
      setElapsed(0);
      setIndex((value) => Math.min(value + 1, PLACEHOLDER_ACTIVITIES.length - 1));
    }, interActivityPauseMs(profile));
  }, [profile]);

  const record = useCallback(
    async (selectedSkillId: string | null, result: string) => {
      if (!activity) return;
      // Written locally FIRST, with a deterministic key. Then posted.
      await outbox.current.enqueue(
        "/play/sessions/placeholder/attempts",
        {
          activity_id: activity.id,
          skill_id: activity.skillId,
          selected_skill_id: selectedSkillId,
          result,
          prompt_level: rung === "initial" ? "independent" : rung,
        },
        attemptKey("placeholder", activity.id, 1),
      );
      await outbox.current.drain();
      advance();
    },
    [activity, rung, advance],
  );

  if (!started) {
    // The caregiver's tap is what performs AudioContext.resume(), so Nour never
    // fails to speak because of a mobile autoplay policy.
    return (
      <div className="grid min-h-screen place-items-center p-6 text-center">
        <div>
          <NourCharacter state="idle" />
          <p className="mt-5 text-lg text-ink-muted">{t("startHint")}</p>
          <button
            type="button"
            data-testid="start-session"
            onClick={() => setStarted(true)}
            className="mt-6 rounded-lg bg-primary px-8 py-4 text-2xl font-semibold text-surface"
            style={{ minBlockSize: `${TOUCH_TARGET_PX}px` }}
          >
            {t("start")}
          </button>
        </div>
      </div>
    );
  }

  if (!activity) {
    return (
      <div data-testid="closing-scene" className="grid min-h-screen place-items-center">
        <div className="text-center">
          <NourCharacter state="celebrating" />
          <p className="mt-5 text-child font-semibold text-ink">{t("closing")}</p>
        </div>
      </div>
    );
  }

  return (
    <div data-testid="play-screen" data-rung={rung} className="min-h-screen">
      <SessionDots total={PLACEHOLDER_ACTIVITIES.length} done={index} />

      <div className="grid place-items-center gap-6 p-4">
        <NourCharacter state={nour} />

        <div className="flex items-center gap-3">
          <button
            type="button"
            data-testid="replay"
            aria-label={t("replay")}
            onClick={() => setNour("speaking")}
            className="rounded-pill bg-primary-soft text-2xl"
            style={{ minInlineSize: `${TOUCH_TARGET_PX}px`, minBlockSize: `${TOUCH_TARGET_PX}px` }}
          >
            <span aria-hidden>🔊</span>
          </button>
          <p data-testid="instruction" className="text-child font-semibold text-ink">
            {activity.instructionAr}
          </p>
        </div>

        <div className="flex flex-wrap justify-center">
          {activity.choices.map((choice) => (
            <ChoiceCard
              key={choice.skillId}
              id={choice.skillId}
              imageUrl={choice.imageUrl}
              altAr={choice.altAr}
              labelAr={choice.labelAr}
              // Only the correct choice is ever highlighted, and only from the
              // second rung. No choice is ever marked wrong.
              highlight={
                choice.correct && rung !== "initial"
                  ? rung === "full_model"
                    ? "lift_glow"
                    : rung === "partial_verbal"
                      ? "pulse_scale"
                      : "pulse"
                  : "none"
              }
              onChoose={(id) =>
                void record(id, choice.correct ? "correct" : "incorrect")
              }
            />
          ))}
        </div>

        <div className="flex w-full items-center justify-between px-2">
          <MicButton label={t("mic")} onCapture={() => void record(null, "correct")} />
          <CaregiverOverrideButton
            label={t("override")}
            onOverride={() => void record(null, "caregiver_confirmed")}
          />
        </div>
      </div>
    </div>
  );
}
