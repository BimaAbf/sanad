"use client";

import { useState } from "react";

import { Card } from "@/components/ui/Card";

/**
 * A report section, and the norm panel.
 *
 * docs/04e §C12: strengths first, always. Growth in the child's own terms.
 * Focus areas as "next steps", never "deficits". DQ and the norm comparison
 * behind a COLLAPSED panel with a one-line explanation of what a DQ is and is
 * not — and a permanent footer saying this is not a medical assessment.
 *
 * The collapse is `<details>` rather than state-driven markup because the
 * requirement is that the panel is closed by DEFAULT and opens on an explicit
 * action. A `useState(false)` that a parent component can initialise to `true`
 * would let a future screen open it for someone who never asked.
 */
export function ReportSection({
  title,
  children,
  testId,
}: {
  title: string;
  children: React.ReactNode;
  testId: string;
}) {
  return (
    <Card as="article" className="mb-5">
      <h2 data-testid={`${testId}-title`} className="mb-3 text-xl font-semibold text-ink">
        {title}
      </h2>
      <div data-testid={testId}>{children}</div>
    </Card>
  );
}

export function NormPanel({
  title,
  explanation,
  children,
}: {
  title: string;
  explanation: string;
  children: React.ReactNode;
}) {
  const [opened, setOpened] = useState(false);
  return (
    <details
      data-testid="norm-panel"
      data-opened={opened}
      className="mt-6 rounded-md border border-border p-4"
      onToggle={(event) => setOpened((event.target as HTMLDetailsElement).open)}
    >
      <summary className="cursor-pointer font-semibold text-ink">{title}</summary>
      <p className="mt-3 text-sm text-ink-muted">{explanation}</p>
      <div data-testid="norm-panel-content" className="mt-3">
        {children}
      </div>
    </details>
  );
}
