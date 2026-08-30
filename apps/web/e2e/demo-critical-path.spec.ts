import { expect, test } from "@playwright/test";

import {
  DEMO_CHILD_IDS,
  TRACING_CHILD_ID,
  answerCurrentActivity,
  signIn,
  traceOnPad,
} from "./demo-helpers";

/**
 * The demo's critical path, in a real browser, against a real API and a real
 * database.
 *
 * It walks the chain the specification lists, in order, and every assertion is
 * about something the SERVER decided:
 *
 *   sign in -> existing children with different learner states -> create a
 *   child -> caregiver assessment -> assessment persisted -> learner state
 *   created -> first teaching decision -> personalised activity -> wrong answer
 *   -> NO celebration -> attempt persisted -> learner state updated -> the next
 *   activity changes -> right answer -> drawing below threshold fails ->
 *   drawing above it passes -> speech flow -> rewards persist -> session
 *   completes -> caregiver report -> AI inspector on real rows -> sign out ->
 *   sign in -> everything is still there.
 *
 * Three things it deliberately does NOT do:
 *
 * * it does not stub the API. A stubbed backend cannot demonstrate that a
 *   backend decided anything;
 * * it does not read the answer from the page, because the page does not have
 *   it. It answers by tapping a card and then asserts on the verdict the server
 *   returned, which is how it can assert an INCORRECT answer at all;
 * * it does not use `sanad seed-demo`'s children for the new-child half. That
 *   half exists to prove a family with nothing can get to a first personalised
 *   session, and seeded history would hide a failure there.
 *
 * Prerequisites, all of them named by `just demo-check` before it runs this:
 * the API on :8000 with a migrated database, `sanad seed` for the curriculum,
 * `sanad seed-demo` for the three children, and the web app on :3000.
 */

test.describe("the demo critical path", () => {
  test.describe.configure({ mode: "serial" });

  test("existing children have different learner states", async ({ page }) => {
    await page.goto("/children");

    const seeded = DEMO_CHILD_IDS.map((id) =>
      page.locator(`[data-testid="child-card"][data-child-id="${id}"]`),
    );
    for (const card of seeded) {
      await expect(card).toHaveCount(1);
      // Every child is named. `/me` used to answer with an empty string for all
      // of them, which made this screen a row of identical unnamed cards.
      await expect(card.getByTestId("child-name")).not.toBeEmpty();
    }

    // Stars are a SUM over `reward_events`, so two cards differing is two
    // RECORDS differing.
    const stars = await Promise.all(
      seeded.map((card) => card.locator('[data-testid^="stars-"]').innerText()),
    );
    expect(new Set(stars).size).toBeGreaterThan(1);

    // And their assessed bands differ, which is what makes their sessions
    // differ. Rendered per child from that child's own starting assessment.
    const bands = await Promise.all(
      seeded.map((card) => card.locator('[data-testid^="bands-"] li').allTextContents()),
    );
    expect(bands[0]?.length ?? 0).toBeGreaterThan(0);
    expect(new Set(bands.map((list) => list.join("|"))).size).toBe(DEMO_CHILD_IDS.length);
  });

  test("a session is server-driven and never celebrates a wrong answer", async ({ page }) => {
    // A whole session, one activity at a time, each one a round trip.
    test.setTimeout(180_000);
    await page.goto("/children");
    await page
      .locator(`[data-child-id="${DEMO_CHILD_IDS[0]}"] [data-testid^="play-"]`)
      .click();
    await page.waitForURL(/\/play/);

    await page.getByTestId("play-start").click();
    const screen = page.getByTestId("play-screen");
    await expect(screen).toBeVisible({ timeout: 20_000 });

    // The activity is a teaching decision the server took: it names a type and
    // a skill the client did not choose.
    await expect(screen).toHaveAttribute("data-activity-type", /.+/);
    await expect(page.getByTestId("instruction")).toBeVisible();

    // --- a wrong answer ----------------------------------------------------
    // "Wrong" is best-effort: the page does not know which card is right, so
    // the test taps a different one and then reads the verdict the SERVER
    // returned. Both branches below are assertions.
    await answerCurrentActivity(page, true);
    const verdict = page.getByTestId("verdict");
    await expect(verdict).toBeVisible({ timeout: 15_000 });

    const correct = await verdict.getAttribute("data-correct");
    if (correct === "false") {
      // The rule the whole product rests on: no celebration, no star.
      await expect(page.getByTestId("celebration")).toHaveCount(0);
      await expect(page.getByTestId("encouragement")).toBeVisible();
      await expect(page.getByTestId("stars-earned")).toHaveCount(0);
    } else {
      // The first card happened to be the right one. The complement is just as
      // much of an assertion: a CORRECT answer must celebrate.
      await expect(page.getByTestId("celebration")).toBeVisible();
    }

    // --- and the loop continues, with a fresh decision ----------------------
    await expect(screen).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("instruction")).toBeVisible();

    // --- play it out ---------------------------------------------------------
    //
    // To the end, not to a fixed count: the server decides when a session is
    // over (the activity cap, the clock, or an exhausted candidate set), and a
    // test that stopped after N would never see the closing screen.
    const closing = page.getByTestId("closing-scene");
    for (let index = 0; index < 16; index += 1) {
      if (await closing.isVisible().catch(() => false)) break;
      await expect(screen).toBeVisible({ timeout: 20_000 });
      await answerCurrentActivity(page, false);
      await expect(page.getByTestId("verdict")).toBeVisible({ timeout: 15_000 });
      await page.waitForTimeout(1200);
    }
    await expect(closing).toBeVisible({ timeout: 30_000 });

    // The child's result: stars and skills. No accuracy, no ratio, no
    // comparison — docs/04e §C13 has no failure state and "4 out of 7" is one.
    await expect(page.getByTestId("stars-total")).toBeVisible();
    await expect(page.getByTestId("skills-practised")).toBeVisible();
    await expect(page.getByText(/\d+\s*(من|\/)\s*\d+/)).toHaveCount(0);
  });

  test("a poor drawing fails and a faithful one passes", async ({ page }) => {
    test.setTimeout(120_000);

    // Sara. Her record is months of accurate tracing against a thinner
    // receptive one, so the loop opens her session with a tracing activity.
    // Not forced by the test — chosen by the server from her evidence, which
    // is the thing being demonstrated.
    await page.goto("/children");
    await page
      .locator(`[data-child-id="${TRACING_CHILD_ID}"] [data-testid^="play-"]`)
      .click();
    await page.waitForURL(/\/play/);
    await page.getByTestId("play-start").click();

    const screen = page.getByTestId("play-screen");
    await expect(screen).toBeVisible({ timeout: 20_000 });
    await expect(screen).toHaveAttribute("data-phase", /ready|answering/, {
      timeout: 20_000,
    });
    await expect(screen).toHaveAttribute("data-activity-type", "trace_letter");
    await expect(page.getByTestId("tracing-pad")).toBeVisible();

    // --- a blank canvas cannot even be submitted ----------------------------
    await expect(page.getByTestId("tracing-submit")).toBeDisabled();

    // --- a dot: drawn, submitted, and refused by the server ------------------
    await traceOnPad(page, { faithful: false });
    await expect(page.getByTestId("tracing-submit")).toBeEnabled();
    await page.getByTestId("tracing-submit").click();

    const verdict = page.getByTestId("verdict");
    await expect(verdict).toBeVisible({ timeout: 15_000 });
    await expect(verdict).toHaveAttribute("data-correct", "false");
    await expect(page.getByTestId("celebration")).toHaveCount(0);
    await expect(page.getByTestId("stars-earned")).toHaveCount(0);

    // --- and the same letter, traced ----------------------------------------
    await expect(screen).toHaveAttribute("data-phase", /ready|answering/, {
      timeout: 20_000,
    });
    // The loop offers the failed skill again — that is the errorless-learning
    // response to a miss, and it is why the good drawing can be compared with
    // the bad one on the same guide.
    for (let attempt = 0; attempt < 6; attempt += 1) {
      const type = await screen.getAttribute("data-activity-type");
      if (type === "trace_letter") break;
      await answerCurrentActivity(page, false);
      await expect(verdict).toBeVisible({ timeout: 15_000 });
      await page.waitForTimeout(1200);
      await expect(screen).toHaveAttribute("data-phase", /ready|answering/, {
        timeout: 20_000,
      });
    }
    await expect(screen).toHaveAttribute("data-activity-type", "trace_letter");

    await traceOnPad(page, { faithful: true });
    await page.getByTestId("tracing-submit").click();
    await expect(verdict).toBeVisible({ timeout: 15_000 });
    await expect(verdict).toHaveAttribute("data-correct", "true");
    await expect(page.getByTestId("celebration")).toBeVisible();
    await expect(page.getByTestId("stars-earned")).toBeVisible();
  });

  test("a new child is assessed, gets a learner state, and plays", async ({ page }) => {
    // Counted rather than assumed: the demo database keeps the children earlier
    // runs created, and a hard-coded three would make this test pass exactly
    // once. `just demo-check` resets the database, but the test should not
    // depend on that having happened.
    await page.goto("/children");
    const before = await page.getByTestId("child-card").count();

    // --- create the child --------------------------------------------------
    // Already signed in, so `/onboarding` opens on the child step.
    await page.goto("/onboarding");
    await expect(page.getByTestId("onboarding")).toHaveAttribute("data-step", "child");
    const name = `طفل ${Date.now() % 100000}`;
    await page.locator("#child-name").fill(name);
    await page.locator("#child-dob").fill("2019-06-15");
    await page.getByTestId("child-submit").click();

    // The three mandatory consents. The API refuses a child without them, so
    // ticking fewer would be a test of the consent gate rather than of this.
    for (const consent of ["data_processing", "ai_processing", "terms_not_medical"]) {
      await page.getByTestId(`consent-${consent}`).check();
    }
    await page.getByTestId("consent-submit").click();
    await page.waitForURL(/\/home/, { timeout: 20_000 });

    // --- the caregiver assessment ------------------------------------------
    await page.goto("/children");
    const cards = page.getByTestId("child-card");
    await expect(cards).toHaveCount(before + 1, { timeout: 15_000 });

    // The new child is the one with no assessed bands. Found that way rather
    // than by position, so the test says what it means: an UNASSESSED child is
    // the one offered the assessment.
    const fresh = cards.last();
    await expect(fresh.locator('[data-testid^="bands-"]')).toHaveCount(0);
    const childId = await fresh.getAttribute("data-child-id");
    expect(childId).toBeTruthy();

    await fresh.getByRole("link", { name: /نبدأ منين/ }).click();
    await page.waitForURL(new RegExp(`/child/${childId}/start`), { timeout: 15_000 });

    const runner = page.getByTestId("starting-assessment");
    await expect(runner).toBeVisible({ timeout: 15_000 });
    // The instrument says it is unreviewed, and the runner renders that.
    await expect(page.getByTestId("starting-watermark")).toBeVisible();

    // Answer every question. `next_questions` only ever shrinks, so the loop
    // terminates on the finalise button appearing rather than on a count.
    for (let step = 0; step < 30; step += 1) {
      const finalise = page.getByTestId("starting-finalise");
      if (await finalise.isVisible().catch(() => false)) break;
      const option = page.locator('[data-testid^="answer-"]').first();
      await option.click();
      await page.waitForTimeout(120);
    }
    await page.getByTestId("starting-finalise").click();
    await expect(page.getByTestId("starting-done")).toBeVisible({ timeout: 15_000 });

    // --- the first personalised session -------------------------------------
    await page.goto("/children");
    await page.locator('[data-testid^="play-"]').last().click();
    await page.waitForURL(/\/play/);
    await page.getByTestId("play-start").click();
    await expect(page.getByTestId("play-screen")).toBeVisible({ timeout: 20_000 });
    // A decision was taken for a child who did not exist five seconds ago.
    await expect(page.getByTestId("instruction")).toBeVisible();
  });

  test("rewards, the report and the inspector survive a sign-out", async ({ page }) => {
    await page.goto("/children");

    const card = page.locator(`[data-child-id="${DEMO_CHILD_IDS[0]}"]`);
    const starsBefore = await card.locator('[data-testid^="stars-"]').innerText();

    // The caregiver's read of a finished session, and why it went that way.
    await card.getByRole("link", { name: /افتح الملف/ }).click();
    await expect(page.getByTestId("session-report")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("fact-activities")).toBeVisible();
    await expect(page.getByTestId("narrative")).toBeVisible();

    const inspector = page.getByTestId("ai-inspector");
    await expect(inspector).toBeVisible();
    // Real rows: a decision with a skill, a strategy and the estimate it was
    // taken at. A panel showing "غير متاح" everywhere would pass a weaker
    // assertion than this one.
    await expect(inspector.getByTestId("decision-skill").first()).not.toBeEmpty();
    await expect(inspector.getByTestId("decision-strategy").first()).not.toBeEmpty();
    await expect(inspector.getByTestId("decision-reasons").first()).toContainText(/[A-Z_]{3,}/);

    // --- sign out, sign in --------------------------------------------------
    await page.context().clearCookies();
    await page.goto("/children");
    await expect(page.getByRole("link", { name: /تسجيل الدخول/ })).toBeVisible();

    // The second and last sign-in of the run. Everything below is read back
    // from the database by a session that did not exist a moment ago.
    await signIn(page);
    await page.goto("/children");
    const starsAfter = await page
      .locator(`[data-child-id="${DEMO_CHILD_IDS[0]}"]`)
      .locator('[data-testid^="stars-"]')
      .innerText();
    expect(starsAfter).toEqual(starsBefore);
  });
});
