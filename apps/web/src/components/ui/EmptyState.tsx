import type { ReactNode } from "react";

/**
 * docs/06 §3: "Empty states are instructional."
 *
 * An empty state that only says "no data" tells a parent their child has done
 * nothing. One that says what to do next tells them where to start, which is
 * the same information without the verdict.
 */
export function EmptyState({
  title,
  body,
  action,
}: {
  title: string;
  body: string;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-lg border border-border bg-surface-alt p-6 text-center">
      <h2 className="text-lg font-semibold text-ink">{title}</h2>
      <p className="mt-2 text-ink-muted">{body}</p>
      {action ? <div className="mt-5 flex justify-center">{action}</div> : null}
    </div>
  );
}
