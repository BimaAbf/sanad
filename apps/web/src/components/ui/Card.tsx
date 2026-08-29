import type { ReactNode } from "react";

export function Card({
  children,
  className = "",
  as: Tag = "section",
}: {
  children: ReactNode;
  className?: string;
  as?: "section" | "article" | "div";
}) {
  return (
    <Tag
      className={`rounded-lg border border-border bg-surface p-5 shadow-1 ${className}`}
    >
      {children}
    </Tag>
  );
}
