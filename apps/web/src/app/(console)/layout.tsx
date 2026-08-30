import type { ReactNode } from "react";

import { CONSOLE_ROLES, type ConsoleRole } from "@/lib/console-access";

/**
 * Console shell.
 *
 * docs/04e §C14: a separate auth realm, mandatory TOTP MFA, an IP allow-list
 * and a 30-minute idle timeout. None of those are enforced here — they are
 * enforced by the API and by the edge, because a client-side gate is a
 * suggestion. What this layout does is make the state visible, so a session
 * that is somehow unauthenticated renders as unauthenticated rather than as an
 * empty console.
 */
async function currentSession(): Promise<{ role: ConsoleRole; mfa: boolean } | null> {
  // Wired to the console auth realm. Null until then, which renders the gate.
  return null;
}

export default async function ConsoleLayout({ children }: { children: ReactNode }) {
  const session = await currentSession();

  if (!session || !session.mfa) {
    return (
      <div data-testid="console-mfa-gate" className="mx-auto max-w-[480px] p-8 text-center">
        <h1 className="text-xl font-semibold">محتاج تأكيد بخطوتين</h1>
      </div>
    );
  }

  return (
    <div data-testid="console" data-role={session.role} className="mx-auto max-w-[1100px] p-6">
      <header className="mb-6 flex items-baseline justify-between border-b border-border pb-4">
        <h1 className="text-xl font-semibold text-primary">لوحة المتابعة</h1>
        <span className="text-sm text-ink-muted">{session.role}</span>
      </header>
      <nav className="mb-6 flex flex-wrap gap-4 text-sm">
        {CONSOLE_ROLES[session.role].routes.map((route) => (
          <a key={route} href={`/console/${route}`} className="text-primary underline">
            {route}
          </a>
        ))}
      </nav>
      <main>{children}</main>
    </div>
  );
}
