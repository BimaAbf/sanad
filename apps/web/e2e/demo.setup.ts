import { expect, test as setup } from "@playwright/test";

import { signIn, STORAGE_STATE } from "./demo-helpers";

/**
 * Sign in once, and share the session with every test in the `demo` project.
 *
 * Not a convenience. `RATE_OTP_PER_PHONE_PER_HOUR` is three, and the critical
 * path has five screens that need a signed-in caregiver — so a suite that
 * signed in per test would rate-limit ITSELF on the fourth, and the failure
 * would read as a broken product rather than as a test that asked for too many
 * codes. One here, and one more in the test that deliberately signs out.
 */
setup("sign in as the demo caregiver", async ({ page }) => {
  await signIn(page);
  await page.goto("/children");
  await expect(page.getByTestId("children-page")).toBeVisible();
  await page.context().storageState({ path: STORAGE_STATE });
});
