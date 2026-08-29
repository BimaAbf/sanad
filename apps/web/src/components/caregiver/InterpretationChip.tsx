"use client";

/**
 * "فهمت إن ده بيحصل بمساعدة — صح؟"
 *
 * docs/04e §C12 item 6: every interpreted verdict is confirmable and
 * correctable in ONE tap. This is the guardrail that makes the AI interpret
 * step safe to ship: the model's reading of a parent's sentence is never
 * written to a clinical record without the parent seeing it in their own words
 * and being able to say no.
 */
export function InterpretationChip({
  text,
  confirmLabel,
  changeLabel,
  onConfirm,
  onChange,
}: {
  text: string;
  confirmLabel: string;
  changeLabel: string;
  onConfirm: () => void;
  onChange: () => void;
}) {
  return (
    <div
      data-testid="interpretation-chip"
      className="mt-5 rounded-md border border-primary bg-primary-soft p-4"
    >
      <p className="text-ink">{text}</p>
      <div className="mt-3 flex gap-3">
        <button
          type="button"
          data-testid="interpretation-confirm"
          onClick={onConfirm}
          className="rounded-md bg-primary px-4 py-2 font-semibold text-surface"
        >
          {confirmLabel}
        </button>
        <button
          type="button"
          data-testid="interpretation-change"
          onClick={onChange}
          className="rounded-md border border-primary px-4 py-2 font-semibold text-primary"
        >
          {changeLabel}
        </button>
      </div>
    </div>
  );
}
