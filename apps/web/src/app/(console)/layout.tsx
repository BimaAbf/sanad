import type { ReactNode } from "react";

/** Clinician console shell. Information-dense; a professional audience. */
export default function ConsoleLayout({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto max-w-[1100px] p-5">
      <header className="mb-5 border-b border-border pb-3">
        <h1 className="text-lg font-semibold text-ink-muted">مِسك · لوحة المتابعة</h1>
      </header>
      <main>{children}</main>
    </div>
  );
}
