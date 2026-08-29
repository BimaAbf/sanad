import { expect, test, type Page } from "@playwright/test";

import {
  CONSOLE_ROLES,
  CONSOLE_ROUTES,
  REASON_REQUIRED_ROUTES,
  canAccess,
  forbiddenPairs,
  type ConsoleRole,
} from "../src/lib/console-access";

/**
 * T14 — the clinician / admin console.
 *
 * ⚠️ NEVER EXECUTED. See child-play.spec.ts.
 *
 * The role matrix is walked exhaustively — every role against every route —
 * rather than sampled. docs/09 P14 asks for exactly that, and the reason is
 * that a permissions bug is invisible on the happy path: the role that should
 * not see child data works perfectly right up until it sees child data.
 */

const ROLES = Object.keys(CONSOLE_ROLES) as ConsoleRole[];

async function signIn(page: Page, role: ConsoleRole, mfa = true) {
  // The console has its own auth realm. The test harness seeds a session
  // directly rather than driving a TOTP flow, and the `mfa` flag is what the
  // MFA test flips.
  await page.goto("/console");
  await page.evaluate(
    ([roleName, mfaOk]) => {
      window.localStorage.setItem("misk.console.test-session", JSON.stringify({ role: roleName, mfa: mfaOk }));
    },
    [role, mfa] as const,
  );
}

for (const route of CONSOLE_ROUTES) {
  test(`/console/${route} is unreachable without MFA`, async ({ page }) => {
    // T14 §1 — every route, not a sample.
    await signIn(page, "admin", false);
    const response = await page.goto(`/console/${route}`);
    const gated =
      response?.status() === 403 || (await page.getByTestId("console-mfa-gate").count()) > 0;
    expect(gated, `/console/${route} rendered without MFA`).toBe(true);
  });
}

for (const { role, route } of forbiddenPairs()) {
  test(`${role} is refused /console/${route}`, async ({ page }) => {
    // T14 §2 — the full matrix.
    await signIn(page, role);
    const response = await page.goto(`/console/${route}`);
    const refused =
      response?.status() === 403 || (await page.getByTestId(route).count()) === 0;
    expect(refused, `${role} reached /console/${route}`).toBe(true);
  });
}

for (const role of ROLES) {
  for (const route of CONSOLE_ROUTES.filter((candidate) => canAccess(role, candidate))) {
    test(`${role} can reach /console/${route}`, async ({ page }) => {
      // The other half of the matrix. A permissions table that refuses
      // everything passes the tests above and ships a console nobody can use.
      await signIn(page, role);
      const response = await page.goto(`/console/${route}`);
      expect(response?.status()).toBeLessThan(400);
    });
  }
}

test("a content_editor cannot reach any child data by any route", async ({ page }) => {
  // Stated separately from the matrix because it is the acceptance criterion in
  // docs/09 P14, and because it must survive someone adding a route.
  await signIn(page, "content_editor");
  for (const route of CONSOLE_ROUTES) {
    const response = await page.goto(`/console/${route}`);
    if (response && response.status() < 400) {
      const body = await page.locator("body").innerText();
      expect(body, `${route} leaked a child identifier`).not.toMatch(
        /child_id|تاريخ الميلاد|اسم الطفل/,
      );
    }
  }
});

test("opening an identified child record requires a typed reason", async ({ page }) => {
  // T14 §3. The audit row is written by the API; what this asserts is that the
  // console cannot request the record without collecting the reason first.
  await signIn(page, "clinician");
  for (const route of REASON_REQUIRED_ROUTES) {
    await page.goto(`/console/${route}/placeholder`);
    await expect(page.getByTestId("access-reason")).toBeVisible();
    await expect(page.getByTestId("access-submit")).toBeDisabled();
    await page.getByTestId("access-reason").fill("مراجعة تقرير قبل الإصدار");
    await expect(page.getByTestId("access-submit")).toBeEnabled();
  }
});

test.skip("a flag toggle reaches the API within 30 seconds", async () => {
  // T14 §5 needs a running API and a real flag cache. Skipped rather than
  // stubbed: a test that toggles a flag in a mock and asserts the mock changed
  // measures nothing about the 30-second guarantee.
});

test.skip("audit_log rejects UPDATE and DELETE", async () => {
  // T14 §4 requires raw SQL against Postgres. Blocked on the Docker daemon —
  // see BLOCKED.md #1. The DDL is written; it has never run.
});
