import { expect, type Page } from "@playwright/test";

/** Where the shared signed-in session is kept between the demo tests. */
export const STORAGE_STATE = "e2e/.auth/caregiver.json";

export const DEMO_PHONE = "01000000000";

/**
 * The three seeded children, by the fixed ids `seeds/demo.py` gives them.
 *
 * Addressed by id rather than by position or count: the demo database keeps
 * whatever earlier runs created, so "the first three cards" is not a stable
 * way to name Ahmed, Laila and Omar.
 */
export const DEMO_CHILD_IDS = [
  "a0000000-0000-4000-8000-000000000001",
  "a0000000-0000-4000-8000-000000000002",
  "a0000000-0000-4000-8000-000000000003",
  "a0000000-0000-4000-8000-000000000004",
] as const;

/**
 * Sara. Her record is months of tracing and a thinner receptive one, so the
 * loop opens her session with a tracing activity — which is what makes the
 * drawing beat of the demo reachable through the browser rather than only
 * through the API.
 */
export const TRACING_CHILD_ID = DEMO_CHILD_IDS[3];
export const API = process.env.SANAD_E2E_API_BASE_URL ?? "http://localhost:8000";

/**
 * Sign in as the demo caregiver, through the real screens.
 *
 * The code comes from `GET /auth/otp/latest`, which the API serves only outside
 * production and only when the null SMS provider is configured — so the code it
 * returns is one that was never sent anywhere. There is no bypassed sign-in
 * here: the form is filled and submitted, and the session that results is the
 * one a caregiver would have.
 */
export async function signIn(page: Page): Promise<void> {
  await page.goto("/onboarding");
  const flow = page.getByTestId("onboarding");
  await expect(flow).toHaveAttribute("data-step", "phone");

  await page.locator("#phone").fill(DEMO_PHONE);
  await page.getByTestId("phone-submit").click();
  // The step attribute, not a timeout: the flow advances on the ACTION's
  // result, so waiting for it is waiting for the API to have answered.
  await advance(page, flow, "otp");

  const response = await page.request.get(`${API}/auth/otp/latest?phone_e164=%2B2${DEMO_PHONE}`);
  expect(
    response.ok(),
    "the API must expose the last dev OTP outside production — see identity/router.py",
  ).toBeTruthy();
  const { code } = (await response.json()) as { code: string };

  await page.locator("#otp").fill(code);
  await page.getByTestId("otp-submit").click();
  await advance(page, flow, "child");
}

/**
 * Wait for the onboarding flow to reach a step, and say why if it does not.
 *
 * The commonest failure is `RATE_OTP_PER_PHONE_PER_HOUR`, which is three: a
 * bare "timed out waiting for data-step" reads as a broken sign-in rather than
 * as a suite that has asked for too many codes. `just demo-check` clears the
 * counter before running, and this turns the remaining case into a sentence.
 */
async function advance(
  page: Page,
  flow: ReturnType<Page["getByTestId"]>,
  step: string,
): Promise<void> {
  try {
    await expect(flow).toHaveAttribute("data-step", step, { timeout: 20_000 });
  } catch (error) {
    const shown = await page
      .getByRole("alert")
      .allInnerTexts()
      .catch(() => [] as string[]);
    const message = shown.filter((text) => text.trim()).join(" · ");
    throw new Error(
      message
        ? `the flow stopped before "${step}": ${message}`
        : `the flow stopped before "${step}" with nothing on screen to say why`,
      { cause: error },
    );
  }
}


/**
 * Answer whatever activity is on screen, the way a child would.
 *
 * Every branch is a real interaction with the real component — a tap on a card,
 * a stroke on the canvas, the caregiver's confirm button. None of them decides
 * whether the answer is right: that is what `getByTestId("verdict")` is for,
 * and the test reads it afterwards.
 *
 * `wrong` is best-effort by design. For a choice activity it taps the last card
 * rather than the first, which is a different card and not necessarily the
 * wrong one — the page does not know which is which, so neither can this. The
 * assertions downstream branch on the verdict the SERVER returned, which is the
 * only honest way to test a client that cannot see the answer.
 */
export async function answerCurrentActivity(page: Page, wrong = false): Promise<void> {
  const screen = page.getByTestId("play-screen");
  // The instruction is spoken before the child may answer, and a tap during
  // that window is ignored on purpose — a fast tap must not answer a question
  // the child has not heard. Waiting for `ready` is waiting for that, not for
  // an arbitrary animation.
  await expect(screen).toHaveAttribute("data-phase", /ready|answering/, { timeout: 20_000 });
  const type = await screen.getAttribute("data-activity-type");

  switch (type) {
    case "select_picture":
    case "listen_choose":
    case "match_pair": {
      const cards = page.locator('[data-testid^="choice-"]');
      await expect(cards.first()).toBeVisible();
      const count = await cards.count();
      await cards.nth(wrong ? count - 1 : 0).click();
      return;
    }
    case "count_objects": {
      const cards = page.locator('[data-testid^="choice-"]');
      await expect(cards.first()).toBeVisible();
      const count = await cards.count();
      await cards.nth(wrong ? count - 1 : 0).click();
      return;
    }
    case "sort_category": {
      // Every card into the first bin. Right or wrong is the server's call.
      const cards = page.locator('[data-testid="sort-cards"] button');
      const bins = page.locator('[data-testid="sort-bins"] button');
      for (let index = (await cards.count()) - 1; index >= 0; index -= 1) {
        await cards.first().click();
        await bins.nth(wrong ? (await bins.count()) - 1 : 0).click();
      }
      await page.getByTestId("sort-submit").click();
      return;
    }
    case "order_sequence": {
      const pool = page.locator('[data-testid="sequence-pool"] button');
      const total = await pool.count();
      for (let index = 0; index < total; index += 1) {
        await pool.nth(wrong ? (await pool.count()) - 1 : 0).click();
      }
      await page.getByTestId("sequence-submit").click();
      return;
    }
    case "speak_word": {
      // Headless Chromium has no speech recogniser, so the microphone is not
      // rendered. The caregiver-confirm button is always there, and it is the
      // documented fallback rather than a test-only path.
      await page.getByTestId("caregiver-confirm").click();
      return;
    }
    case "trace_letter": {
      await traceOnPad(page, { faithful: !wrong });
      await page.getByTestId("tracing-submit").click();
      return;
    }
    default:
      throw new Error(`no way to answer an activity of type ${type ?? "(none)"}`);
  }
}

/**
 * Draw on the tracing canvas with real pointer events.
 *
 * `faithful` walks the guide the server sent; the other draws a single short
 * stroke in the corner, which the scorer rejects as too short. Both go through
 * `dispatchEvent` rather than `mouse.move`, because the pad listens for
 * `pointerdown`/`pointermove` and Playwright's mouse API emits mouse events
 * only in some engines.
 */
export async function traceOnPad(
  page: Page,
  { faithful }: { faithful: boolean },
): Promise<void> {
  const pad = page.getByTestId("tracing-pad");
  await expect(pad).toBeVisible();
  const box = await pad.boundingBox();
  expect(box).not.toBeNull();

  const path: [number, number][] = faithful
    ? await page.evaluate(() => {
        const raw = document.querySelector('[data-testid="play-screen"]');
        // The guide is drawn from the same numbers the server stored, and the
        // component keeps them in a data attribute for exactly this.
        const encoded = raw?.getAttribute("data-reference-path") ?? "[]";
        const strokes = JSON.parse(encoded) as number[][][];
        return strokes.flat().map(([x, y]) => [x ?? 0, y ?? 0] as [number, number]);
      })
    : [
        [0.5, 0.5],
        [0.505, 0.505],
      ];

  const { x, y, width, height } = box!;
  await page.mouse.move(x + (path[0]?.[0] ?? 0) * width, y + (path[0]?.[1] ?? 0) * height);
  await pad.dispatchEvent("pointerdown", { pointerId: 1, isPrimary: true, button: 0 });
  for (const [px, py] of path) {
    await pad.dispatchEvent("pointermove", {
      pointerId: 1,
      isPrimary: true,
      clientX: x + px * width,
      clientY: y + py * height,
    });
  }
  await pad.dispatchEvent("pointerup", { pointerId: 1, isPrimary: true });
}
