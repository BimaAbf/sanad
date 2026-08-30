/**
 * T14 §2 — "walk EVERY route with each of the four roles; assert 403 wherever
 * the role lacks permission. A content_editor must not reach any child data."
 *
 * The Playwright version walks the running app. This version walks the table
 * the app and the API both render from, so a role definition that is wrong is
 * caught before a browser is involved — and, more usefully, so the expected
 * answer exists somewhere other than in the code that enforces it.
 */
import { describe, expect, it } from "vitest";

import {
  CHILD_DATA_ROUTES,
  CONSOLE_ROLES,
  CONSOLE_ROUTES,
  REASON_REQUIRED_ROUTES,
  canAccess,
  childDataLeaks,
  forbiddenPairs,
  unreachableRoutes,
  type ConsoleRole,
} from "./console-access";

const ROLES = Object.keys(CONSOLE_ROLES) as ConsoleRole[];

describe("the role table", () => {
  it("has exactly the four documented roles", () => {
    expect([...ROLES].sort()).toEqual(["admin", "clinician", "content_editor", "ops"]);
  });

  it("covers every route with at least one role", () => {
    // A route no role can reach is a typo far more often than it is a lockout.
    expect(unreachableRoutes()).toEqual([]);
  });

  it("gives admin everything and nobody else everything", () => {
    expect(CONSOLE_ROLES.admin.routes).toHaveLength(CONSOLE_ROUTES.length);
    for (const role of ROLES.filter((r) => r !== "admin")) {
      expect(CONSOLE_ROLES[role].routes.length, role).toBeLessThan(CONSOLE_ROUTES.length);
    }
  });
});

describe("child data", () => {
  it("is reachable only by clinician and admin", () => {
    const allowed = ROLES.filter((role) => CONSOLE_ROLES[role].childData);
    expect([...allowed].sort()).toEqual(["admin", "clinician"]);
  });

  it("a content_editor cannot reach ANY child-data route", () => {
    for (const route of CHILD_DATA_ROUTES) {
      expect(canAccess("content_editor", route), route).toBe(false);
    }
  });

  it("an ops session cannot reach ANY child-data route", () => {
    for (const route of CHILD_DATA_ROUTES) {
      expect(canAccess("ops", route), route).toBe(false);
    }
  });

  it("no role marked childData:false is granted a child-data route", () => {
    // The invariant, checked structurally rather than route by route, so a
    // future route added to `ops` cannot slip past the two tests above.
    expect(childDataLeaks()).toEqual([]);
  });

  it("identified-child access requires a typed reason", () => {
    expect(REASON_REQUIRED_ROUTES).toContain("children");
  });
});

describe("the 403 matrix", () => {
  it("is fully enumerated, and every entry really is denied", () => {
    const pairs = forbiddenPairs();
    expect(pairs.length).toBeGreaterThan(0);
    for (const { role, route } of pairs) {
      expect(canAccess(role, route), `${role} -> ${route}`).toBe(false);
    }
  });

  it("covers every role and route combination exactly once", () => {
    const allowed = ROLES.flatMap((role) =>
      CONSOLE_ROUTES.filter((route) => canAccess(role, route)).map(
        (route) => `${role}:${route}`,
      ),
    );
    const denied = forbiddenPairs().map(({ role, route }) => `${role}:${route}`);
    expect(allowed.length + denied.length).toBe(ROLES.length * CONSOLE_ROUTES.length);
    expect(new Set([...allowed, ...denied]).size).toBe(ROLES.length * CONSOLE_ROUTES.length);
  });

  it("denies anything a role does not list, rather than allowing it", () => {
    // The default matters more than any single entry: a route added next year
    // is forbidden to every non-admin role until someone grants it on purpose.
    // Checked against a route name that is not in the table at all.
    for (const role of ROLES.filter((r) => r !== "admin")) {
      expect(canAccess(role, "a-route-nobody-has-defined" as never), role).toBe(false);
    }
  });

  it("the only roles listing the identified-child route are the two with childData", () => {
    const listing = ROLES.filter((role) => CONSOLE_ROLES[role].routes.includes("children"));
    expect([...listing].sort()).toEqual(["admin", "clinician"]);
  });
});
