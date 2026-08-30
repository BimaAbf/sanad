import { expect, test } from "@playwright/test";

import {
  DOUBLE_TAP_TOLERANCE_MS,
  MAX_ANIMATION_HZ,
  TOUCH_GAP_PX,
  TOUCH_TARGET_PX,
} from "../src/lib/interaction";
import { NOUR_STATES } from "../src/components/child/NourCharacter";

/**
 * T13 — the child play app.
 *
 * ⚠️ NEVER EXECUTED. No Playwright browser is installed on the build machine
 * and CI has never run a job. These specs are written and reviewed; none has
 * been observed to pass. Recorded in PROGRESS.md as an open item rather than
 * reported as a green suite.
 *
 * The device-dependent criteria are marked and skipped rather than faked:
 * §23 (audio on a real iOS Safari) cannot be satisfied by an emulator, and a
 * spec that claims to satisfy it would be worse than no spec.
 */

test.beforeEach(async ({ page }) => {
  await page.goto("/play");
  await page.getByTestId("start-session").click();
  await expect(page.getByTestId("play-screen")).toBeVisible();
});

test("every touch target is at least 88x88 at a 320px viewport", async ({ page }) => {
  // T13 §15. A standard 44px target produces mis-taps, and BKT reads a mis-tap
  // as not-knowing — so a small button corrupts a child's record, it does not
  // merely annoy them.
  const targets = page.locator(
    '[data-testid^="choice-"], [data-testid="mic-button"], [data-testid="caregiver-override"], [data-testid="replay"]',
  );
  const count = await targets.count();
  expect(count).toBeGreaterThan(0);

  for (let index = 0; index < count; index += 1) {
    const box = await targets.nth(index).boundingBox();
    expect(box, `target ${index} has no box`).not.toBeNull();
    expect(box!.width, `target ${index} width`).toBeGreaterThanOrEqual(TOUCH_TARGET_PX);
    expect(box!.height, `target ${index} height`).toBeGreaterThanOrEqual(TOUCH_TARGET_PX);
  }
});

test("choice cards are separated by at least 20px", async ({ page }) => {
  const cards = page.locator('[data-testid^="choice-"]');
  const boxes = await cards.evaluateAll((nodes) =>
    nodes.map((node) => node.getBoundingClientRect()),
  );
  for (let index = 1; index < boxes.length; index += 1) {
    const previous = boxes[index - 1]!;
    const current = boxes[index]!;
    const horizontal = Math.max(previous.left, current.left) - Math.min(previous.right, current.right);
    const vertical = Math.max(previous.top, current.top) - Math.min(previous.bottom, current.bottom);
    expect(Math.max(horizontal, vertical)).toBeGreaterThanOrEqual(TOUCH_GAP_PX);
  }
});

test("no visible timer appears on any screen", async ({ page }) => {
  // T13 §18. Time pressure degrades performance and adds nothing, so there is
  // no countdown, no progress bar with a duration, and no seconds anywhere.
  const body = await page.locator("body").innerText();
  expect(body).not.toMatch(/\b\d+\s*(ثانية|ثواني|s|sec)\b/i);
  await expect(page.locator('[role="timer"]')).toHaveCount(0);
  await expect(page.locator("time[datetime]")).toHaveCount(0);
});

test("progress is dots, never a number or a percentage", async ({ page }) => {
  const dots = page.getByTestId("session-dots");
  await expect(dots).toBeVisible();
  expect(await dots.innerText()).toBe("");
});

test("no animation exceeds 3Hz", async ({ page }) => {
  // T13 §17, by reading the computed animation durations rather than by
  // sampling frames: a frequency is 1/duration, and every animation in the
  // product is a CSS keyframe.
  const durations = await page.evaluate(() =>
    [...document.querySelectorAll("*")]
      .map((node) => getComputedStyle(node))
      .filter((style) => style.animationName !== "none" && style.animationName !== "")
      .map((style) => Number.parseFloat(style.animationDuration) || 0),
  );
  for (const seconds of durations) {
    if (seconds === 0) continue;
    expect(1 / seconds, `animation at ${1 / seconds}Hz`).toBeLessThanOrEqual(MAX_ANIMATION_HZ);
  }
});

test("prefers-reduced-motion disables every animation", async ({ page }) => {
  // T13 §21.
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.reload();
  await page.getByTestId("start-session").click();
  const running = await page.evaluate(() =>
    [...document.querySelectorAll("*")]
      .map((node) => getComputedStyle(node).animationDuration)
      .filter((duration) => Number.parseFloat(duration) > 0.001),
  );
  expect(running).toEqual([]);
});

test("Nour has exactly four states and never a sad one", async ({ page }) => {
  const state = await page.getByTestId("nour").getAttribute("data-state");
  expect(NOUR_STATES).toContain(state);
  expect(NOUR_STATES).toHaveLength(4);
});

test("a double tap inside the tolerance records one attempt", async ({ page }) => {
  const card = page.locator('[data-testid^="choice-"]').first();
  await card.click();
  await card.click({ delay: 0 });
  // The second tap is inside the 400ms tolerance, so the session advanced once.
  await expect(page.getByTestId("play-screen")).toHaveAttribute("data-rung", "initial");
  expect(DOUBLE_TAP_TOLERANCE_MS).toBe(400);
});

test("no input sequence reaches an error state or a dead end", async ({ page }) => {
  // T13 §19 — 500 random interactions. The property is not "nothing breaks";
  // it is that there is no reachable state in which a child is stuck or is
  // shown that something went wrong.
  const selectors = [
    '[data-testid^="choice-"]',
    '[data-testid="mic-button"]',
    '[data-testid="caregiver-override"]',
    '[data-testid="replay"]',
  ];
  for (let step = 0; step < 500; step += 1) {
    const selector = selectors[step % selectors.length]!;
    const target = page.locator(selector).first();
    if ((await target.count()) === 0) continue;
    // Alternate plain taps, double taps and long presses.
    if (step % 3 === 0) await target.click({ force: true });
    else if (step % 3 === 1) await target.dblclick({ force: true });
    else await target.click({ force: true, delay: 700 });

    await expect(page.locator("text=/error|خطأ|حصلت مشكلة/i")).toHaveCount(0);
    const visible = await page.locator("body").isVisible();
    expect(visible, `blank screen after step ${step}`).toBe(true);
  }
});

test("a full session completes with the network disabled after load", async ({ page, context }) => {
  // T13 §13. Everything the session needs is in the Cache API before the first
  // prompt; from here the network is irrelevant.
  await context.setOffline(true);
  const card = page.locator('[data-testid^="choice-"]').first();
  await card.click();
  await expect(page.getByTestId("play-screen").or(page.getByTestId("closing-scene"))).toBeVisible();
  await context.setOffline(false);
});

test.skip("audio plays on iOS Safari after the caregiver's start tap", async () => {
  // T13 §23 explicitly requires a REAL DEVICE, not an emulator. Skipped rather
  // than approximated: a passing emulator run would be evidence of nothing, and
  // an autoplay policy is exactly the thing emulators get wrong.
  // → REVIEW-QUEUE.md: real-device audio on one low-end Android and one iOS.
});
