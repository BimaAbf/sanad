import type { InputHTMLAttributes, ReactNode } from "react";

/**
 * docs/06 §3: "Labels above fields (Arabic labels are long), inline validation
 * on blur, never on keystroke."
 *
 * Validating on keystroke means telling someone their phone number is wrong
 * while they are still typing it, which in Arabic — where the label already
 * takes a full line — leaves the form shouting at a person mid-word.
 */
export function Field({
  label,
  help,
  error,
  id,
  children,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  help?: string;
  error?: string;
  id: string;
  children?: ReactNode;
}) {
  const helpId = help ? `${id}-help` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  return (
    <div className="mb-5">
      <label htmlFor={id} className="mb-2 block font-semibold text-ink">
        {label}
      </label>
      {help ? (
        <p id={helpId} className="mb-2 text-sm text-ink-muted">
          {help}
        </p>
      ) : null}
      {children ?? (
        <input
          {...props}
          id={id}
          aria-describedby={[helpId, errorId].filter(Boolean).join(" ") || undefined}
          aria-invalid={error ? true : undefined}
          className="w-full rounded-md border border-border bg-surface px-4 py-3 text-base"
        />
      )}
      {error ? (
        <p id={errorId} role="alert" className="mt-2 text-sm text-attention">
          {error}
        </p>
      ) : null}
    </div>
  );
}
