import type { ReactNode } from "react";

/**
 * Child app shell. No dark mode by design (docs/06 §2): predictability beats
 * preference, and inverted contrast on illustrated content is worse. Targets are
 * 88px, above the 80px requirement.
 */
export default function PlayLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-surface p-6 text-child">
      <main>{children}</main>
    </div>
  );
}
