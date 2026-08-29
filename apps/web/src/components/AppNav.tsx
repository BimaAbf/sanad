"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { CAREGIVER_TOUCH_TARGET_PX } from "@/lib/interaction";

export interface NavLink {
  href: string;
  label: string;
}

/**
 * The caregiver app's navigation. There was none.
 *
 * Every page in this app rendered under a layout that was a title and nothing
 * else, and no page contained a single `<Link>`. That is the whole reason the
 * app felt unresponsive: there was nothing to click that went anywhere.
 *
 * A client component only because the current route decides which item is
 * marked current, and `aria-current="page"` is not something to approximate —
 * a screen reader user navigating by landmark has no other way to know where
 * they are.
 */
export function AppNav({ links }: { links: NavLink[] }) {
  const pathname = usePathname();

  return (
    <nav aria-label="أقسام التطبيق">
      <ul className="flex flex-wrap gap-2">
        {links.map((link) => {
          const current = pathname === link.href;
          return (
            <li key={link.href}>
              <Link
                href={link.href}
                aria-current={current ? "page" : undefined}
                className={`inline-flex items-center rounded-pill px-4 py-2 text-base transition-colors ${
                  current
                    ? "bg-primary-soft font-semibold text-primary"
                    : "text-ink-muted hover:text-primary"
                }`}
                style={{ minBlockSize: `${CAREGIVER_TOUCH_TARGET_PX}px` }}
              >
                {link.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
