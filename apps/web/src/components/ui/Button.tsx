import type { ButtonHTMLAttributes, ReactNode } from "react";

import { CAREGIVER_TOUCH_TARGET_PX } from "@/lib/interaction";

type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-primary text-surface hover:opacity-90",
  secondary: "bg-primary-soft text-primary hover:opacity-90",
  ghost: "bg-transparent text-primary underline underline-offset-4",
  // "danger" is a two-step control everywhere it appears (docs/06 §3), so the
  // colour is `attention` rather than red. Red reads as failure, and the only
  // thing here that can fail is an adult deleting their own data on purpose.
  danger: "bg-transparent text-attention border border-attention",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  children: ReactNode;
}

/**
 * The caregiver button.
 *
 * `min-height` and `min-inline-size` are set from the token rather than from a
 * Tailwind size class so the 48px floor cannot be overridden by a utility
 * further down the cascade. docs/06 §5 makes it a hard requirement, and a
 * requirement that a `className` prop can undo is a suggestion.
 *
 * Logical properties only — stylelint fails the build on `margin-left` and
 * friends, and this is an RTL-first product.
 */
export function Button({ variant = "primary", className = "", ...props }: ButtonProps) {
  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center rounded-md px-5 py-3 text-base font-semibold transition-opacity disabled:opacity-50 ${VARIANTS[variant]} ${className}`}
      style={{
        minBlockSize: `${CAREGIVER_TOUCH_TARGET_PX}px`,
        minInlineSize: `${CAREGIVER_TOUCH_TARGET_PX}px`,
        ...props.style,
      }}
    />
  );
}
