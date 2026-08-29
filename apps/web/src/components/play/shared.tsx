"use client";

import type { Highlight } from "@/components/child/ChoiceCard";
import { TOUCH_TARGET_PX } from "@/lib/interaction";
import type { ManifestActivity } from "@/lib/manifest";

/**
 * The pieces every game shares.
 *
 * The five activity kinds are five different screens, but they are the same
 * *product*, and these are the parts that make that true: one speaker button in
 * one place, one instruction line in one typeface, one way to record an answer.
 * A child who has learned where the speaker is in `listen_point` has learned
 * where it is in all five.
 */

/** docs/01 §1 — the `attempt_result` enum. */
export type AttemptResult =
  | "correct"
  | "incorrect"
  | "no_response"
  | "accepted_on_effort"
  | "caregiver_confirmed";

/** Copy is passed in rather than read from a hook, so games render in tests. */
export interface PlayLabels {
  replay: string;
  mic: string;
  override: string;
  sayTogether: string;
  next: string;
}

export interface GameProps {
  activity: ManifestActivity;
  /** From the prompt ladder. Applies only to the correct choice, ever. */
  highlight: Highlight;
  /** The card the child last tapped, so the tap is acknowledged on screen. */
  chosenId: string | null;
  labels: PlayLabels;
  /** How wide a picture is on this screen. Set once, by the shell. */
  cardSize: number;
  onAnswer: (selectedSkillId: string | null, result: AttemptResult) => void;
  onReplay: () => void;
}

/**
 * The instruction: spoken, written, and replayable.
 *
 * All three, always. docs/06 §4 — "instructions ≤ 5 words, spoken and written
 * and illustrated" — and the replay button is what makes the spoken half
 * usable, because a child who missed it has no other way back to it and asking
 * an adult is not a route the product may depend on.
 */
export function InstructionBubble({
  text,
  replayLabel,
  onReplay,
}: {
  text: string;
  replayLabel: string;
  onReplay: () => void;
}) {
  return (
    <div className="flex w-full items-center justify-center gap-3">
      <button
        type="button"
        data-testid="replay"
        aria-label={replayLabel}
        onClick={onReplay}
        className="grid shrink-0 place-items-center rounded-pill bg-accent-soft text-3xl transition-transform duration-fast active:scale-95"
        style={{
          minInlineSize: `${TOUCH_TARGET_PX}px`,
          minBlockSize: `${TOUCH_TARGET_PX}px`,
        }}
      >
        <SpeakerIcon />
      </button>
      <p
        data-testid="instruction"
        className="text-child font-semibold leading-tight text-ink"
      >
        {text}
      </p>
    </div>
  );
}

/** Drawn rather than an emoji: an emoji is a different glyph on every phone. */
function SpeakerIcon() {
  return (
    <svg
      viewBox="0 0 48 48"
      aria-hidden="true"
      focusable="false"
      style={{ inlineSize: "38px", blockSize: "38px" }}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path
        d="M8 19h7l10-8v26l-10-8H8Z"
        fill="var(--c-accent)"
        stroke="#2B2B2B"
        strokeWidth="3"
      />
      <path
        d="M31 18c4 3 4 9 0 12M37 13c7 6 7 16 0 22"
        stroke="var(--c-accent)"
        strokeWidth="3.5"
        fill="none"
      />
    </svg>
  );
}

/**
 * The row a choice sits in.
 *
 * Two columns, fixed — not a wrapping flex row.
 *
 * The difference matters at 320 px, which is the width the touch-target
 * assertion runs at and the width of the cheapest phone a family is likely to
 * have. A flex row wraps two choices onto two lines there, and a child then has
 * to scroll to see the second option, or worse, never learns it is there. Two
 * choices are meant to be compared, and they can only be compared side by side.
 *
 * Four choices become 2 × 2 for the same reason.
 *
 * The >= 20 px gap docs/06 §5 requires is `gap-5` (24 px) on this container,
 * NOT a margin on each card. That distinction was worth a bug: a `width: 100%`
 * grid item with an inline margin resolves its width against the whole grid
 * area and then overflows by the margin, so two cards that each "had" a 10 px
 * margin measured as touching. Grid gap is the only thing that actually puts
 * space between grid items, and mis-taps are the failure this rule exists to
 * prevent — BKT reads a mis-tap as not-knowing, so cards that touch corrupt a
 * child's record rather than merely looking cramped.
 */
export const CHOICE_GAP_CLASS = "gap-5";

export function ChoiceRow({ children }: { children: React.ReactNode }) {
  return (
    <div
      className={`mx-auto grid w-full max-w-[520px] grid-cols-2 items-stretch ${CHOICE_GAP_CLASS}`}
    >
      {children}
    </div>
  );
}

/** `true` when this choice is the one the ladder is currently pointing at. */
export function highlightFor(
  activity: ManifestActivity,
  skillId: string,
  highlight: Highlight,
): Highlight {
  const choice = activity.choices.find((candidate) => candidate.skill_id === skillId);
  // Only ever the correct one, and never at the first rung. No choice is ever
  // marked wrong — there is no styling in this product for wrong.
  return choice?.correct ? highlight : "none";
}
