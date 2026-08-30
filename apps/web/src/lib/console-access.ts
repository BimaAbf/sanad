/**
 * Console RBAC, as a table.
 *
 * docs/04e §C14 and docs/09 P14: four roles, least privilege, and **child data
 * visible only to clinician and admin**. The acceptance criterion is to walk
 * every route with every role and assert a 403 wherever the role lacks
 * permission — which is only a meaningful test if the expected answer is
 * written down somewhere independent of the code that enforces it.
 *
 * This is that table. The API enforces it; the console renders from it; the
 * test walks it. A route missing from every role is unreachable, which the
 * test also checks, because an unreachable route is usually a typo rather than
 * a deliberate lockout.
 *
 * Pure. No React, no fetch.
 */

export type ConsoleRole = "clinician" | "content_editor" | "ops" | "admin";

/** Every console route, by its path segment under /console. */
export const CONSOLE_ROUTES = [
  "escalations",
  "items",
  "content",
  "reports",
  "ai-calls",
  "guardrail-events",
  "flags",
  "cost",
  "children",
] as const;

export type ConsoleRoute = (typeof CONSOLE_ROUTES)[number];

/**
 * Routes that expose an identified child record.
 *
 * docs/09 P14: "A content_editor session cannot reach any child data." Naming
 * the set explicitly means that adding a route which shows child data is a
 * deliberate edit here, not an oversight in four separate role lists.
 */
export const CHILD_DATA_ROUTES: readonly ConsoleRoute[] = [
  "escalations",
  "reports",
  "children",
];

/** Routes whose access must write an audit_log row with a typed reason. */
export const REASON_REQUIRED_ROUTES: readonly ConsoleRoute[] = ["children"];

export interface RoleDefinition {
  routes: readonly ConsoleRoute[];
  /** May this role see an identified child record at all? */
  childData: boolean;
}

export const CONSOLE_ROLES: Record<ConsoleRole, RoleDefinition> = {
  clinician: {
    routes: ["escalations", "reports", "items", "children"],
    childData: true,
  },
  content_editor: {
    // Deliberately no `reports`: a report is about one identified child.
    routes: ["items", "content"],
    childData: false,
  },
  ops: {
    // Escalation SLA is an ops concern, but the *contents* of an escalation are
    // a child's words. Ops gets the queue's timing view through `cost` and
    // `flags` and the AI explorers, not the queue itself.
    routes: ["ai-calls", "guardrail-events", "flags", "cost"],
    childData: false,
  },
  admin: {
    routes: [...CONSOLE_ROUTES],
    childData: true,
  },
};

export function canAccess(role: ConsoleRole, route: ConsoleRoute): boolean {
  return CONSOLE_ROLES[role].routes.includes(route);
}

/**
 * Every (role, route) pair that must return 403.
 *
 * Generated rather than listed, so a new route is automatically forbidden to
 * every role that was not explicitly given it — the safe default.
 */
export function forbiddenPairs(): { role: ConsoleRole; route: ConsoleRoute }[] {
  const pairs: { role: ConsoleRole; route: ConsoleRoute }[] = [];
  for (const role of Object.keys(CONSOLE_ROLES) as ConsoleRole[]) {
    for (const route of CONSOLE_ROUTES) {
      if (!canAccess(role, route)) pairs.push({ role, route });
    }
  }
  return pairs;
}

/** Roles that may reach a child-data route despite `childData: false`. Must be empty. */
export function childDataLeaks(): string[] {
  const leaks: string[] = [];
  for (const [role, definition] of Object.entries(CONSOLE_ROLES) as [
    ConsoleRole,
    RoleDefinition,
  ][]) {
    if (definition.childData) continue;
    for (const route of definition.routes) {
      if (CHILD_DATA_ROUTES.includes(route)) leaks.push(`${role} -> ${route}`);
    }
  }
  return leaks;
}

/** Routes no role can reach. Usually a typo, never a deliberate lockout. */
export function unreachableRoutes(): ConsoleRoute[] {
  return CONSOLE_ROUTES.filter(
    (route) =>
      !(Object.keys(CONSOLE_ROLES) as ConsoleRole[]).some((role) => canAccess(role, route)),
  );
}
