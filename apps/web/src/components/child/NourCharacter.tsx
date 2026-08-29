import { INK, K, PRIMARY, PRIMARY_SOFT } from "@/components/art/frame";

/**
 * Nour, in exactly four states.
 *
 * docs/09 P13 fixes the set: idle, speaking, listening, celebrating. Four is a
 * ceiling, not a starting point — every extra state is another thing a child
 * has to interpret, and this character exists to reduce interpretation, not to
 * be expressive.
 *
 * There is deliberately no "sad", "confused" or "wrong" state. The product has
 * no failure states, so the character has no face for one.
 *
 * ## What each state is allowed to change
 *
 * Only the mouth, the eyes and one accessory. The head, the body, the colours
 * and the position are identical in all four, so the child is looking at one
 * character doing different things rather than four pictures. That constraint
 * is why the drawing is inline SVG and not four image files: four files drift.
 *
 * ## Motion
 *
 * `idle` does not move. A character that never stops moving competes with the
 * activity for a child's attention, and the activity has to win. `speaking`
 * moves only the mouth, `celebrating` is one 800 ms bounce, and both are killed
 * by the `prefers-reduced-motion` rule in globals.css.
 */
export type NourState = "idle" | "speaking" | "listening" | "celebrating";

export const NOUR_STATES: readonly NourState[] = [
  "idle",
  "speaking",
  "listening",
  "celebrating",
];

/**
 * PLACEHOLDER — agent-written Arabic, not reviewed. These are read aloud by a
 * caregiver's screen reader, not by the child. → REVIEW-QUEUE.md
 */
const LABEL_AR: Record<NourState, string> = {
  idle: "نور مستنية",
  speaking: "نور بتتكلم",
  listening: "نور بتسمع",
  celebrating: "نور مبسوطة",
};

function Eyes({ state }: { state: NourState }) {
  if (state === "celebrating") {
    // Closed, curved-up eyes. The universal drawn shorthand for delight, and
    // the one expression that cannot be misread as surprise or alarm.
    return (
      <>
        <path
          d="M40 56a9 9 0 0 1 16 0M64 56a9 9 0 0 1 16 0"
          stroke={INK}
          strokeWidth="4"
          fill="none"
          strokeLinecap="round"
        />
      </>
    );
  }
  const radius = state === "listening" ? 7 : 6;
  return (
    <>
      <circle cx="48" cy="58" r={radius} fill={INK} />
      <circle cx="72" cy="58" r={radius} fill={INK} />
      <circle cx="45.5" cy="55.5" r="2.2" fill={K.white} />
      <circle cx="69.5" cy="55.5" r="2.2" fill={K.white} />
    </>
  );
}

function Mouth({ state }: { state: NourState }) {
  if (state === "speaking") {
    return (
      <ellipse
        cx="60"
        cy="78"
        rx="9"
        ry="8"
        fill={INK}
        style={{
          transformOrigin: "60px 78px",
          animationName: "sanad-speak",
          animationDuration: "520ms",
          animationIterationCount: "infinite",
        }}
      />
    );
  }
  if (state === "celebrating") {
    return (
      <>
        <path d="M46 74a14 14 0 0 0 28 0Z" fill={INK} />
        <path d="M50 82a10 6 0 0 0 20 0Z" fill={K.pink} />
      </>
    );
  }
  return (
    <path
      d="M50 76a11 11 0 0 0 20 0"
      stroke={INK}
      strokeWidth="4"
      fill="none"
      strokeLinecap="round"
    />
  );
}

export function NourCharacter({
  state = "idle",
  size = 132,
}: {
  state?: NourState;
  size?: number;
}) {
  return (
    <div
      data-testid="nour"
      data-state={state}
      role="img"
      aria-label={LABEL_AR[state]}
      className="grid place-items-center rounded-pill"
      style={{
        inlineSize: `${size}px`,
        blockSize: `${size}px`,
        backgroundColor: PRIMARY_SOFT,
        // 800ms is 1.25Hz, well under the 3Hz ceiling, and it runs only while
        // celebrating. Everything else is still.
        animationName: state === "celebrating" ? "sanad-cheer" : "none",
        animationDuration: "800ms",
        animationIterationCount: "2",
      }}
    >
      <svg
        viewBox="0 0 120 120"
        xmlns="http://www.w3.org/2000/svg"
        aria-hidden="true"
        focusable="false"
        style={{ inlineSize: "86%", blockSize: "86%" }}
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {/* Hair, behind the face. */}
        <path
          d="M20 62c0-26 18-44 40-44s40 18 40 44c0 8-2 14-4 18-2-10-6-16-10-20-8 8-16 12-26 12s-18-4-26-12c-4 4-8 10-10 20-2-4-4-10-4-18Z"
          fill="#3E2C23"
          stroke={INK}
          strokeWidth="3"
        />
        <circle cx="60" cy="64" r="36" fill={K.skin} stroke={INK} strokeWidth="3.5" />
        {/* Cheeks — the whole reason this face reads as warm rather than blank. */}
        <ellipse cx="34" cy="72" rx="8" ry="6" fill={K.pink} opacity="0.55" />
        <ellipse cx="86" cy="72" rx="8" ry="6" fill={K.pink} opacity="0.55" />
        <path
          d="M22 58c0-24 17-40 38-40s38 16 38 40c-3-9-7-14-11-18-8 8-16 12-27 12s-19-4-27-12c-4 4-8 9-11 18Z"
          fill="#3E2C23"
          stroke={INK}
          strokeWidth="3.5"
        />
        <Eyes state={state} />
        <Mouth state={state} />

        {/* The one accessory that changes: a cupped ear while listening. */}
        {state === "listening" ? (
          <>
            <path
              d="M96 56c8-2 12 4 12 10s-4 12-12 12"
              stroke={PRIMARY}
              strokeWidth="4"
              fill="none"
            />
            <path d="M104 44c10 8 10 28 0 36" stroke={PRIMARY} strokeWidth="4" fill="none" />
          </>
        ) : null}

        {/* And two sparkles while celebrating. Two, not a burst. */}
        {state === "celebrating" ? (
          <>
            <path
              d="M16 30l3 7 7 3-7 3-3 7-3-7-7-3 7-3ZM104 26l2.5 6 6 2.5-6 2.5-2.5 6-2.5-6-6-2.5 6-2.5Z"
              fill={K.yellow}
              stroke={INK}
              strokeWidth="2"
            />
          </>
        ) : null}
      </svg>
    </div>
  );
}
