import { fraction, rangeCopyKey, type Range } from "@/lib/progress-range";

/**
 * The PGEE runner's progress indicator.
 *
 * docs/04e §C12: "narrowing progress range, never a bar that can move
 * backwards". The monotonicity lives in `lib/progress-range.ts`; this component
 * only renders what that module has already clamped, so there is no path by
 * which a render can widen it.
 *
 * `aria-valuetext` carries the range in words, because a screen reader
 * announcing "38%" of an adaptive assessment is announcing a number that has no
 * stable meaning.
 */
export function ProgressRange({ range, label }: { range: Range; label: string }) {
  const percent = Math.round(fraction(range) * 100);
  return (
    <div
      data-testid="progress-range"
      data-min-remaining={range.minRemaining}
      data-max-remaining={range.maxRemaining}
      data-fraction={fraction(range).toFixed(4)}
      data-copy-key={rangeCopyKey(range)}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={percent}
      aria-valuetext={label}
    >
      <div className="h-2 w-full overflow-hidden rounded-pill bg-surface-alt">
        <div
          className="h-full rounded-pill bg-primary transition-[inline-size]"
          style={{ inlineSize: `${percent}%` }}
        />
      </div>
      <p className="mt-2 text-sm text-ink-muted">{label}</p>
    </div>
  );
}
