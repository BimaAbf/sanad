"use client";

import { useId, useRef } from "react";

import { SkillArt } from "@/components/art/SkillArt";
import { PULSE_HZ, TOUCH_TARGET_PX, shouldCountTap } from "@/lib/interaction";

export type Highlight = "none" | "pulse" | "pulse_scale" | "lift_glow";

/**
 * One picture a child can tap.
 *
 * Four things here are requirements rather than styling, and each is written so
 * a later `className` cannot undo it:
 *
 * * **>= 88 x 88 px.** docs/06 §5. A standard 44 px target produces mis-taps,
 *   and BKT would read a mis-tap as not-knowing — so a small button does not
 *   merely annoy a child, it corrupts their record. The >= 20 px gap that rule
 *   also asks for belongs to `ChoiceRow`, which explains why.
 * * **No disabled state and no error state.** There is nothing a child can tap
 *   that is wrong, so there is no styling for wrong. `chosen` acknowledges the
 *   tap; it is not a verdict on it, and it looks the same whichever card it is.
 * * **Text is always present beside the picture.** docs/04e §C13 — the visual
 *   channel is this population's strength, so it carries everything.
 * * **Double-tap tolerance.** A second tap on the same card within 400 ms is a
 *   tremor or a perseveration, not a second answer.
 *
 * The highlight animations are all at 1.5 Hz — half the 3 Hz ceiling — and are
 * disabled wholesale by the `prefers-reduced-motion` block in globals.css.
 */
export function ChoiceCard({
  id,
  imageUrl,
  altAr,
  labelAr,
  highlight = "none",
  chosen = false,
  size = 120,
  onChoose,
  now = () => Date.now(),
}: {
  id: string;
  /** From the manifest when C05 supplies one; the bundled art draws it if not. */
  imageUrl?: string | undefined;
  altAr: string;
  labelAr: string;
  highlight?: Highlight;
  chosen?: boolean;
  size?: number;
  onChoose: (id: string) => void;
  now?: () => number;
}) {
  const lastTap = useRef<{ target: string; atMs: number } | null>(null);
  const describedBy = useId();

  const handle = () => {
    const at = now();
    if (!shouldCountTap(id, at, lastTap.current)) return;
    lastTap.current = { target: id, atMs: at };
    onChoose(id);
  };

  const lifted = highlight === "pulse_scale" || highlight === "lift_glow";

  return (
    <button
      type="button"
      data-testid={`choice-${id}`}
      data-highlight={highlight}
      data-chosen={chosen || undefined}
      onClick={handle}
      // A long press counts as a tap on release (docs/04e §C13), which is the
      // browser's default for click. The context menu is suppressed so a long
      // press does not open one on top of the activity.
      onContextMenu={(event) => event.preventDefault()}
      aria-describedby={describedBy}
      className="flex w-full flex-col items-center justify-center gap-2 overflow-hidden rounded-lg border-4 bg-surface p-3 transition-transform duration-base"
      style={{
        minInlineSize: `${TOUCH_TARGET_PX}px`,
        minBlockSize: `${TOUCH_TARGET_PX}px`,
        borderColor: chosen || lifted ? "var(--c-primary)" : "var(--c-border)",
        animationName:
          highlight === "none" ? "none" : highlight === "lift_glow" ? "sanad-glow" : "sanad-pulse",
        animationDuration: `${1000 / PULSE_HZ}ms`,
        animationIterationCount: "infinite",
        transform: lifted || chosen ? "scale(1.04)" : undefined,
      }}
    >
      <SkillArt code={id} imageUrl={imageUrl} size={size} />
      {/* `break-words` because "كوباية مية" at 32px is wider than a card at
          320px, and a label that overflows its card is a label a child cannot
          read. It wraps; the card grows. */}
      <span className="break-words text-center text-child font-semibold leading-tight text-ink">
        {labelAr}
      </span>
      {/* The description, not the name. The accessible NAME is the visible
          label, so "tap أحمر" works with voice control; the longer alt text is
          the description a screen reader adds after it. */}
      <span id={describedBy} className="sr-only">
        {altAr}
      </span>
    </button>
  );
}
