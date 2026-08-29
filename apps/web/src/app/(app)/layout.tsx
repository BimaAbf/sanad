import { getTranslations } from "next-intl/server";
import Link from "next/link";
import type { ReactNode } from "react";

import { AppNav, type NavLink } from "@/components/AppNav";
import { getActiveChildId } from "@/lib/session";

/**
 * Caregiver app shell. Comfortable density, 17px/1.9 body text, dark mode
 * supported (unlike the child app).
 *
 * The nav is built here rather than in each page so that the child-scoped links
 * are impossible to render without a child id — when there is no child yet, the
 * only route offered is the one that adds one.
 */
export default async function CaregiverLayout({ children }: { children: ReactNode }) {
  const t = await getTranslations("nav");
  const tApp = await getTranslations("app");
  const childId = await getActiveChildId();

  const links: NavLink[] = [
    { href: "/home", label: t("today") },
    ...(childId
      ? [
          { href: `/child/${childId}/coach`, label: t("coach") },
          { href: `/child/${childId}/skills`, label: t("skills") },
          { href: `/child/${childId}/journey`, label: t("journey") },
          { href: `/child/${childId}/settings`, label: t("settings") },
        ]
      : []),
    { href: "/play", label: t("play") },
  ];

  return (
    <div className="mx-auto max-w-[640px] p-5">
      <header className="mb-6 border-b border-border pb-4">
        <Link href="/" className="text-2xl font-semibold text-primary">
          {tApp("title")}
        </Link>
        <div className="mt-4">
          <AppNav links={links} />
        </div>
      </header>
      <main>{children}</main>
    </div>
  );
}
