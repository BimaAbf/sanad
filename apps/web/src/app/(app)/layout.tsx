import type { ReactNode } from "react";

/**
 * Caregiver app shell. Comfortable density, 17px/1.9 body text, dark mode
 * supported (unlike the child app).
 */
export default function CaregiverLayout({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto max-w-[640px] p-5">
      <header className="mb-6 border-b border-border pb-4">
        <h1 className="text-2xl font-semibold text-primary">مِسك</h1>
      </header>
      <main>{children}</main>
    </div>
  );
}
