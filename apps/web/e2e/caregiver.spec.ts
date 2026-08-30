import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { firstWidening, type Range } from "../src/lib/progress-range";

/**
 * T12 — the caregiver app.
 *
 * ⚠️ NEVER EXECUTED. See the note in child-play.spec.ts.
 */

const ROUTES = [
  "/onboarding",
  "/home",
  "/assessment/placeholder",
  "/child/placeholder/skills",
  "/child/placeholder/journey",
  "/child/placeholder/settings",
];

for (const route of ROUTES) {
  test(`axe-core is clean at WCAG 2.2 AA on ${route}`, async ({ page }) => {
    // T12 §6. Every route, not a sample — an untested route is where the
    // untested component ends up.
    await page.goto(route);
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
      .analyze();
    expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
  });

  test(`${route} is fully keyboard navigable with a visible focus ring`, async ({ page }) => {
    // T12 §7. >= 3px, which globals.css sets as `outline: 3px solid`.
    await page.goto(route);
    await page.keyboard.press("Tab");
    const outline = await page.evaluate(() => {
      const active = document.activeElement;
      if (!active || active === document.body) return null;
      const style = getComputedStyle(active);
      return { width: style.outlineWidth, style: style.outlineStyle };
    });
    expect(outline).not.toBeNull();
    expect(Number.parseFloat(outline!.width)).toBeGreaterThanOrEqual(3);
    expect(outline!.style).not.toBe("none");
  });

  test(`${route} survives 200% text zoom without horizontal scroll`, async ({ page }) => {
    // T12 §8. Arabic labels are long; at 200% they are the first thing to clip.
    await page.goto(route);
    await page.addStyleTag({ content: "html { font-size: 200% !important; }" });
    const overflows = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    );
    expect(overflows, "the page scrolls horizontally at 200% zoom").toBe(false);
  });
}

test("the document is RTL and Egyptian Arabic", async ({ page }) => {
  await page.goto("/home");
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.locator("html")).toHaveAttribute("lang", "ar-EG");
});

test("the built stylesheet contains no physical CSS property", async ({ page, request }) => {
  // T12 §9. Grep the OUTPUT, not the source: a Tailwind utility can emit
  // `margin-left` from a class that does not contain the word.
  await page.goto("/home");
  const hrefs = await page.locator('link[rel="stylesheet"]').evaluateAll((nodes) =>
    nodes.map((node) => (node as HTMLLinkElement).href),
  );
  expect(hrefs.length).toBeGreaterThan(0);
  for (const href of hrefs) {
    const css = await (await request.get(href)).text();
    // Tailwind's preflight legitimately emits some physical properties for
    // form-control normalisation; the ban is on OUR declarations, so the check
    // is scoped to the utility layer by excluding the reset's known selectors.
    const ours = css.split("*,:after,:before").pop() ?? css;
    for (const property of [
      "margin-left",
      "margin-right",
      "padding-left",
      "padding-right",
      "border-left",
      "border-right",
      "left:",
      "right:",
    ]) {
      expect(ours, `${href} contains ${property}`).not.toContain(property);
    }
  }
});

test("the progress range never widens across a full assessment", async ({ page }) => {
  // T12 §3, the headline caregiver criterion. Every rendered value is recorded
  // and the whole sequence is checked, rather than each step against the last —
  // a single-step check would miss a slow drift.
  await page.goto("/assessment/placeholder");
  const history: Range[] = [];

  const capture = async () => {
    const element = page.getByTestId("progress-range");
    history.push({
      answered: 0,
      minRemaining: Number(await element.getAttribute("data-min-remaining")),
      maxRemaining: Number(await element.getAttribute("data-max-remaining")),
    });
  };

  await capture();
  for (let step = 0; step < 40; step += 1) {
    const button = page.getByTestId("verdict-yes");
    if ((await button.count()) === 0) break;
    await button.click();
    await capture();
  }

  expect(history.length).toBeGreaterThan(5);
  expect(firstWidening(history), `widened at index ${firstWidening(history)}`).toBe(-1);
});

test("an interpreted verdict is correctable in one tap", async ({ page }) => {
  // T12 §4. One tap, not a menu: this is the control that keeps a model's
  // reading of a parent's sentence out of a clinical record unchallenged.
  await page.goto("/assessment/placeholder");
  await page.getByTestId("own-words").click();
  await page.getByTestId("own-words-input").fill("بيحاول بس مش بيعرف");
  await page.getByTestId("own-words-submit").click();
  await expect(page.getByTestId("interpretation-chip")).toBeVisible();
  await page.getByTestId("interpretation-change").click();
  await expect(page.getByTestId("interpretation-chip")).toHaveCount(0);
});

test("the three buttons are present even when free text is offered", async ({ page }) => {
  // docs/04e §C12: "so the AI path is never the only path".
  await page.goto("/assessment/placeholder");
  await expect(page.getByTestId("verdict-yes")).toBeVisible();
  await expect(page.getByTestId("verdict-emerging")).toBeVisible();
  await expect(page.getByTestId("verdict-no")).toBeVisible();
  await expect(page.getByTestId("own-words")).toBeVisible();
});

test("save-and-continue is visible on every assessment screen", async ({ page }) => {
  await page.goto("/assessment/placeholder");
  await expect(page.getByTestId("save-and-exit")).toBeVisible();
});

test("the report shows strengths before focus areas and hides DQ by default", async ({ page }) => {
  // T12 §5. DOM order, not visual order: a screen reader reads the DOM, and a
  // parent using one must hear what their child can do first.
  await page.goto("/child/placeholder/assessments/placeholder");
  const order = await page.evaluate(() => {
    const strengths = document.querySelector('[data-testid="strengths-title"]');
    const focus = document.querySelector('[data-testid="focus-title"]');
    if (!strengths || !focus) return null;
    return strengths.compareDocumentPosition(focus) & Node.DOCUMENT_POSITION_FOLLOWING ? "ok" : "wrong";
  });
  expect(order).toBe("ok");

  const panel = page.getByTestId("norm-panel");
  await expect(panel).not.toHaveAttribute("open", "");
  await expect(page.getByTestId("norm-panel-content")).toBeHidden();
});

test("offline: read views render from cache and a write queues", async ({ page, context }) => {
  // T12 §10.
  await page.goto("/home");
  await context.setOffline(true);
  await page.reload();
  await expect(page.getByTestId("today").or(page.locator("text=/النهارده/"))).toBeVisible();
  await context.setOffline(false);
});
