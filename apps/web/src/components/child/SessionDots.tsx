/**
 * Progress as dots, never as a number or a percentage (docs/06 §4).
 *
 * "3 of 8" is a number a child cannot use and an adult reads as a score. Dots
 * say the same thing — some done, some left — with nothing to compare against.
 */
export function SessionDots({ total, done }: { total: number; done: number }) {
  return (
    <div
      data-testid="session-dots"
      className="flex justify-center gap-2 p-4"
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={total}
      aria-valuenow={done}
      // The child never reads this; the caregiver's screen reader does.
      aria-label="تقدّم اللعبة"
    >
      {Array.from({ length: total }, (_, index) => (
        <span
          key={index}
          data-done={index < done}
          className="block rounded-pill"
          style={{
            inlineSize: "14px",
            blockSize: "14px",
            backgroundColor: index < done ? "var(--c-primary)" : "var(--c-border)",
          }}
        />
      ))}
    </div>
  );
}
