import type { ReactNode } from "react";

/**
 * The drawing frame every illustration in the product shares.
 *
 * ## Why the artwork is SVG in the bundle rather than files on a CDN
 *
 * docs/04c has the session manifest carry `https://cdn/…/red.webp` per choice,
 * and it will. But the child app has a hard offline guarantee — "the child app
 * never starts a session it cannot finish" (docs/06 §7) — and a raster asset
 * pipeline is the part of that guarantee most likely to be missing on the day
 * of a pilot. Vector art that is already in the JS bundle cannot 404, cannot
 * arrive at the wrong size, needs no signed URL, and costs ~0.4 KB gzipped per
 * drawing against the 220 KB route budget.
 *
 * When real illustrations exist, `SkillArt` prefers a manifest `imageUrl` and
 * falls back to these. Nothing here has to be deleted for that to happen.
 *
 * ## The drawing rules, which are accessibility rules
 *
 * * One object, centred, filling most of the frame. A scene has to be parsed;
 *   an object is recognised.
 * * A heavy `INK` outline on every shape. Figure/ground separation is doing the
 *   work here, not colour — the palette is one of the things calm mode takes
 *   away, and a drawing that stops being legible without its colour was relying
 *   on the wrong channel.
 * * No text inside a drawing. Labels live outside it, in the real font, where
 *   they can be selected, zoomed and read aloud.
 * * `aria-hidden` always: the label beside the picture is the accessible name,
 *   so a screen reader that announced both would say everything twice.
 */

export const INK = "#2B2B2B";
export const STROKE = 3.5;

/** The brand pair, for the few drawings that are UI rather than an object. */
export const PRIMARY = "#1F6F5C";
export const PRIMARY_SOFT = "#E4F2EE";

export const K = {
  red: "#D93A2B",
  blue: "#1C6BBF",
  yellow: "#F0B429",
  green: "#2E8B4A",
  purple: "#7B4FA8",
  orange: "#E87722",
  pink: "#D9538C",
  brown: "#8B5E3C",
  black: "#2B2B2B",
  white: "#FFFFFF",
  skin: "#F3C9A0",
  skinDeep: "#C98A5B",
  paper: "#FFFFFF",
  steel: "#C9D4D9",
  wood: "#C98A4B",
} as const;

/**
 * Every drawing is authored in a 120×120 box and scaled by CSS, so a choice
 * card at 88 px and a hero at 220 px are the same file at two sizes rather than
 * two drawings that drifted apart.
 */
export function ArtFrame({ children }: { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 120 120"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      focusable="false"
      style={{ inlineSize: "100%", blockSize: "100%", display: "block" }}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {children}
    </svg>
  );
}
