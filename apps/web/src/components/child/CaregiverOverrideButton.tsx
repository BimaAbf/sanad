"use client";

import { TOUCH_TARGET_PX } from "@/lib/interaction";

/**
 * "قالها صح ✅"
 *
 * docs/04d §3 calls this the single control that makes the expressive path
 * usable for a child whose speech no machine can transcribe. It is PERMANENTLY
 * visible on every expressive activity — not revealed after a failure, because
 * revealing it after a failure would mean there was a failure.
 *
 * It is also the data-collection mechanism for the ASR fine-tune (docs/12
 * §3.2), which is why it records rather than merely advancing.
 */
export function CaregiverOverrideButton({
  onOverride,
  label,
}: {
  onOverride: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      data-testid="caregiver-override"
      onClick={onOverride}
      className="rounded-md border-2 border-primary bg-primary-soft px-5 py-3 text-lg font-semibold text-primary"
      style={{ minBlockSize: `${TOUCH_TARGET_PX}px` }}
    >
      {label}
    </button>
  );
}
