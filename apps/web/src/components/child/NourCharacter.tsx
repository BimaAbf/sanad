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
 */
export type NourState = "idle" | "speaking" | "listening" | "celebrating";

export const NOUR_STATES: readonly NourState[] = [
  "idle",
  "speaking",
  "listening",
  "celebrating",
];

const LABEL_AR: Record<NourState, string> = {
  idle: "نور مستنية",
  speaking: "نور بتتكلم",
  listening: "نور بتسمع",
  celebrating: "نور مبسوطة",
};

export function NourCharacter({ state = "idle" }: { state?: NourState }) {
  return (
    <div
      data-testid="nour"
      data-state={state}
      role="img"
      aria-label={LABEL_AR[state]}
      className="grid place-items-center rounded-pill bg-primary-soft"
      style={{
        inlineSize: "120px",
        blockSize: "120px",
        // 1.5Hz, half the 3Hz ceiling, and only while celebrating. Idle is
        // still: a character that never stops moving is one more thing
        // competing for a child's attention with the activity.
        animationName: state === "celebrating" ? "misk-pulse" : "none",
        animationDuration: "666ms",
        animationIterationCount: "infinite",
      }}
    >
      <span aria-hidden className="text-4xl">
        {state === "listening" ? "👂" : state === "celebrating" ? "🎉" : "🙂"}
      </span>
    </div>
  );
}
