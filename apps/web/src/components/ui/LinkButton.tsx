import Link from "next/link";
import type { ReactNode } from "react";

import { BUTTON_BASE, VARIANTS, type Variant } from "@/components/ui/Button";
import { CAREGIVER_TOUCH_TARGET_PX } from "@/lib/interaction";

/**
 * A link that looks and measures like a Button.
 *
 * It shares `BUTTON_BASE` and `VARIANTS` with Button rather than copying them,
 * because two independently maintained sets of button classes is how the 48px
 * touch floor ends up holding on one of them. Navigation is an anchor, not a
 * button with an onClick — that is what makes it work with a middle click, a
 * long press, and a screen reader's link list.
 */
export function LinkButton({
  href,
  variant = "primary",
  className = "",
  children,
}: {
  href: string;
  variant?: Variant;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Link
      href={href}
      className={`${BUTTON_BASE} ${VARIANTS[variant]} ${className}`}
      style={{
        minBlockSize: `${CAREGIVER_TOUCH_TARGET_PX}px`,
        minInlineSize: `${CAREGIVER_TOUCH_TARGET_PX}px`,
      }}
    >
      {children}
    </Link>
  );
}
