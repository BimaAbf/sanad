import type { ReactNode } from "react";

/**
 * The one card surface.
 *
 * `data-testid` is forwarded explicitly rather than by spreading `...rest`.
 * Spreading would let a caller override `className` and quietly lose the
 * border, the padding and the shadow that make a card a card; naming the one
 * attribute tests need keeps the surface closed and still lets a test find it.
 *
 * It had neither before, and the consequence was not cosmetic: a `data-testid`
 * on a `<Card>` was silently dropped, so an end-to-end test looking for the
 * screen it marked waited for an element that could never exist.
 */
export function Card({
  children,
  className = "",
  as: Tag = "section",
  "data-testid": testId,
}: {
  children: ReactNode;
  className?: string;
  as?: "section" | "article" | "div";
  "data-testid"?: string;
}) {
  return (
    <Tag
      data-testid={testId}
      className={`rounded-lg border border-border bg-surface p-5 shadow-1 ${className}`}
    >
      {children}
    </Tag>
  );
}
