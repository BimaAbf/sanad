"use client";

import { SkillArt } from "@/components/art/SkillArt";
import { NourCharacter } from "@/components/child/NourCharacter";
import type { SkillCategory } from "@/content/curriculum";
import { WORLDS } from "@/content/worlds";
import { TOUCH_TARGET_PX } from "@/lib/interaction";
import { arabicDigits } from "@/lib/numerals";

/**
 * The three screens either side of the activities: start, celebration, closing.
 *
 * They carry more of the product's warmth than the activities do, and less of
 * its measurement — nothing here is recorded, so nothing here has to be
 * cautious. The constraint they do share with the activities is that none of
 * them is on a clock a child can lose: the start screen waits for a caregiver,
 * the celebration is a fixed 800 ms of calm and not a thing to sit through, and
 * the closing scene never ends on its own.
 */

export interface WorldLabels {
  colors: string;
  body_parts: string;
  social: string;
  household: string;
  numbers: string;
  letters: string;
}

/**
 * The start screen.
 *
 * The tap on "ابدأ" is what performs the audio unlock, so Nour never fails to
 * speak because of a mobile autoplay policy. That is the whole reason this
 * screen exists rather than the session starting on load — it is not a menu, it
 * is a gesture the browser requires, dressed as a beginning.
 *
 * The world picker underneath is for the caregiver, and is labelled as the
 * secondary path it is. Left to itself the session comes from the adaptive
 * engine (docs/04c §C06), which is the right default; but a parent who wants to
 * do letters today should not have to want it through a scheduling algorithm.
 */
export function StartScreen({
  title,
  hint,
  startLabel,
  pickLabel,
  worldLabels,
  selected,
  onToggleWorld,
  onStart,
}: {
  title: string;
  hint: string;
  startLabel: string;
  pickLabel: string;
  worldLabels: WorldLabels;
  selected: readonly SkillCategory[];
  onToggleWorld: (category: SkillCategory) => void;
  onStart: () => void;
}) {
  return (
    <div className="mx-auto flex min-h-screen max-w-[560px] flex-col items-center justify-center gap-6 p-5 text-center">
      <NourCharacter state="idle" size={148} />
      <h1 className="text-3xl font-semibold text-primary">{title}</h1>
      <p className="text-lg text-ink-muted">{hint}</p>

      <button
        type="button"
        data-testid="start-session"
        onClick={onStart}
        className="rounded-lg bg-primary px-8 py-4 text-child font-semibold text-surface shadow-2 transition-transform duration-fast active:scale-95"
        style={{ minBlockSize: `${TOUCH_TARGET_PX}px`, minInlineSize: "220px" }}
      >
        {startLabel}
      </button>

      <section aria-labelledby="worlds-heading" className="w-full">
        <h2 id="worlds-heading" className="mb-3 text-base text-ink-muted">
          {pickLabel}
        </h2>
        <ul className="grid grid-cols-3 gap-3">
          {WORLDS.map(({ category, faceCode, tint, count }) => {
            const on = selected.includes(category);
            return (
              <li key={category}>
                <button
                  type="button"
                  data-testid={`world-${category}`}
                  aria-pressed={on}
                  onClick={() => onToggleWorld(category)}
                  className="flex w-full flex-col items-center gap-1 rounded-lg border-4 p-2 transition-transform duration-fast active:scale-95"
                  style={{
                    minBlockSize: `${TOUCH_TARGET_PX}px`,
                    backgroundColor: tint,
                    borderColor: on ? "var(--c-primary)" : "transparent",
                  }}
                >
                  <SkillArt code={faceCode} size={52} />
                  <span className="text-sm font-semibold text-ink">
                    {worldLabels[category]}
                  </span>
                  <span className="text-xs text-ink-muted">{arabicDigits(count)}</span>
                </button>
              </li>
            );
          })}
        </ul>
      </section>
    </div>
  );
}

/**
 * The celebration between activities.
 *
 * docs/06 §4: "celebration is proportionate — a brief character animation and
 * one warm phrase. Confetti and fanfare become noise within a week and add
 * cognitive load." So: Nour, one word, and the 800 ms of calm the next activity
 * needs anyway. No score, no streak, no stars out of five.
 */
export function Celebration({ praise }: { praise: string }) {
  return (
    <div
      data-testid="celebration"
      className="flex min-h-[60vh] flex-col items-center justify-center gap-5"
    >
      <NourCharacter state="celebrating" size={160} />
      <p className="text-child font-semibold text-primary">{praise}</p>
    </div>
  );
}

/**
 * The closing scene.
 *
 * One sticker per activity, each one the picture of the thing that was
 * practised. It is a record rather than a reward: a parent can look at it and
 * see what the last ten minutes were about, and a child can see the lion they
 * met. That is also why there is no total and no percentage — docs/06 §4 keeps
 * numbers off this app entirely.
 *
 * It has no auto-advance. The session is over; nothing should be counting.
 */
export function ClosingScene({
  message,
  stickers,
  againLabel,
  onAgain,
}: {
  message: string;
  stickers: string[];
  againLabel: string;
  onAgain: () => void;
}) {
  return (
    <div
      data-testid="closing-scene"
      className="flex min-h-screen flex-col items-center justify-center gap-6 p-5 text-center"
    >
      <NourCharacter state="celebrating" size={148} />
      <p className="text-child font-semibold text-ink">{message}</p>

      {/* 44px stickers, four to a row at 320px. A ten-activity board that
          needs scrolling to see puts the "play again" button below the fold,
          and the last thing a session should ask of a child is a scroll. */}
      <ul className="flex max-w-[300px] flex-wrap justify-center gap-3">
        {stickers.map((code, index) => (
          <li
            key={`${code}-${index}`}
            className="grid place-items-center rounded-pill bg-surface-alt p-1"
            style={{
              animationName: "sanad-land",
              animationDuration: "400ms",
              // Staggered so they arrive one after another rather than all at
              // once. Capped, so a ten-activity session does not take four
              // seconds to finish landing.
              animationDelay: `${Math.min(index, 8) * 90}ms`,
              animationFillMode: "both",
            }}
          >
            <SkillArt code={code} size={44} />
          </li>
        ))}
      </ul>

      <button
        type="button"
        data-testid="play-again"
        onClick={onAgain}
        className="rounded-lg bg-primary px-8 py-4 text-xl font-semibold text-surface"
        style={{ minBlockSize: `${TOUCH_TARGET_PX}px` }}
      >
        {againLabel}
      </button>
    </div>
  );
}
