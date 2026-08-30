"use client";

import { Button } from "@/components/ui/Button";

/**
 * The three big buttons, plus the two discreet ones.
 *
 * docs/04e §C12: "The three buttons are always present even when free text is
 * offered, so the AI path is never the only path." That is the reason this is
 * a component and not a prop on the free-text field — the buttons cannot be
 * conditionally hidden if they are the thing rendering the question.
 *
 * There is no colour-coding: no green for "yes", no amber for "emerging". The
 * doc calls anxiety management a design requirement, and a parent answering
 * fifty-five questions about their child must not be able to read a verdict off
 * the palette as they go.
 */
export type Verdict = "yes" | "emerging" | "no" | "unsure" | "not_applicable";

export function VerdictButtons({
  labels,
  onAnswer,
  disabled = false,
}: {
  labels: Record<Verdict, string>;
  onAnswer: (verdict: Verdict) => void;
  disabled?: boolean;
}) {
  return (
    <div>
      <div className="grid gap-3">
        {(["yes", "emerging", "no"] as const).map((verdict) => (
          <Button
            key={verdict}
            variant="secondary"
            disabled={disabled}
            data-testid={`verdict-${verdict}`}
            onClick={() => onAnswer(verdict)}
            className="w-full text-lg"
          >
            {labels[verdict]}
          </Button>
        ))}
      </div>
      <div className="mt-4 flex justify-center gap-5">
        {(["unsure", "not_applicable"] as const).map((verdict) => (
          <button
            key={verdict}
            type="button"
            disabled={disabled}
            data-testid={`verdict-${verdict}`}
            onClick={() => onAnswer(verdict)}
            className="text-sm text-ink-muted underline underline-offset-4"
          >
            {labels[verdict]}
          </button>
        ))}
      </div>
    </div>
  );
}
