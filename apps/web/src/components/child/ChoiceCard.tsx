"use client";

import { useRef } from "react";

import {
  PULSE_HZ,
  TOUCH_GAP_PX,
  TOUCH_TARGET_PX,
  shouldCountTap,
} from "@/lib/interaction";

export type Highlight = "none" | "pulse" | "pulse_scale" | "lift_glow";

/**
 * One picture a child can tap.
 *
 * Three things here are requirements rather than styling, and each is written
 * so a later `className` cannot undo it:
 *
 * * **>= 88 x 88 px with a >= 20 px gap.** docs/06 §5. A standard 44 px target
 *   produces mis-taps, and BKT would read a mis-tap as not-knowing — so a small
 *   button does not merely annoy a child, it corrupts their record.
 * * **No disabled state and no error state.** There is nothing a child can tap
 *   that is wrong, so there is no styling for wrong.
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
  onChoose,
  now = () => Date.now(),
}: {
  id: string;
  imageUrl: string;
  altAr: string;
  labelAr: string;
  highlight?: Highlight;
  onChoose: (id: string) => void;
  now?: () => number;
}) {
  const lastTap = useRef<{ target: string; atMs: number } | null>(null);

  const handle = () => {
    const at = now();
    if (!shouldCountTap(id, at, lastTap.current)) return;
    lastTap.current = { target: id, atMs: at };
    onChoose(id);
  };

  return (
    <button
      type="button"
      data-testid={`choice-${id}`}
      data-highlight={highlight}
      onClick={handle}
      // A long press counts as a tap on release (docs/04e §C13), which is the
      // browser's default for click. The context menu is suppressed so a long
      // press does not open one on top of the activity.
      onContextMenu={(event) => event.preventDefault()}
      className="flex flex-col items-center justify-center gap-3 rounded-lg border-4 border-border bg-white p-4"
      style={{
        minInlineSize: `${TOUCH_TARGET_PX}px`,
        minBlockSize: `${TOUCH_TARGET_PX}px`,
        marginInline: `${TOUCH_GAP_PX / 2}px`,
        animationName: highlight === "none" ? "none" : "misk-pulse",
        animationDuration: `${1000 / PULSE_HZ}ms`,
        animationIterationCount: "infinite",
        transform: highlight === "pulse_scale" || highlight === "lift_glow" ? "scale(1.04)" : undefined,
        boxShadow: highlight === "lift_glow" ? "0 0 0 6px var(--c-primary-soft)" : undefined,
      }}
    >
      {/* A plain <img>, not next/image, on purpose: the manifest supplies
          absolute R2/CDN URLs that the session already preloaded into the Cache
          API. Routing them through the image optimiser would re-fetch them at
          render time and defeat the offline guarantee — the child app must be
          able to finish a session with the network off. */}
      <img src={imageUrl} alt={altAr} className="max-w-full" width={160} height={160} />
      {/* Text is ALWAYS present alongside the image (docs/04e §C13): the visual
          channel is this population's strength, so it carries everything. */}
      <span className="text-child font-semibold text-ink">{labelAr}</span>
    </button>
  );
}
