/**
 * docs/06 §3: "Skeletons, never spinners. A spinner on a slow connection reads
 * as broken."
 *
 * The shimmer is deliberately absent under `prefers-reduced-motion` — globals
 * kills the animation, and a static grey block is still a better signal than a
 * spinner.
 */
export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div aria-hidden className="space-y-3">
      {Array.from({ length: lines }, (_, index) => (
        <div
          key={index}
          className="h-5 animate-pulse rounded-sm bg-surface-alt"
          style={{ inlineSize: index === lines - 1 ? "60%" : "100%" }}
        />
      ))}
    </div>
  );
}
