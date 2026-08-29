import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright for both client apps.
 *
 * Two projects rather than one, because the child app is held to stricter rules
 * than the caregiver app — 88px targets instead of 48, 7:1 contrast instead of
 * 4.5:1 — and the viewport that matters for the child is a 320px phone, which
 * is the width at which the touch-target assertion is actually interesting.
 *
 * NOT YET EXECUTED. No browser binary is installed on the build machine and CI
 * has never run. Every spec under e2e/ is written and reviewed; none has been
 * observed to pass or fail. See PROGRESS.md — this is recorded as an open item,
 * not as a green suite.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.SANAD_E2E_BASE_URL ?? "http://localhost:3000",
    locale: "ar-EG",
    timezoneId: "Africa/Cairo",
    trace: "on-first-retry",
  },
  // `exactOptionalPropertyTypes` is on, so an absent web server is an empty
  // list rather than `undefined`: CI points SANAD_E2E_BASE_URL at a deployed
  // preview and must not also start a dev server.
  webServer: process.env.SANAD_E2E_BASE_URL
    ? []
    : [
        {
          command: "pnpm dev",
          url: "http://localhost:3000/",
          reuseExistingServer: !process.env.CI,
          timeout: 120_000,
        },
      ],
  projects: [
    {
      name: "caregiver",
      testMatch: /caregiver|a11y/,
      use: { ...devices["Pixel 5"] },
    },
    {
      name: "child",
      testMatch: /child|play/,
      // 320px is the width at which the 88px-target assertion is meaningful.
      // A 412px phone passes trivially.
      use: { ...devices["Pixel 5"], viewport: { width: 320, height: 720 } },
    },
  ],
});
