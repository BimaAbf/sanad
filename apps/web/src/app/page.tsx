import { getTranslations } from "next-intl/server";

import { SkillArt } from "@/components/art/SkillArt";
import { WORLDS } from "@/content/worlds";
import { arabicDigits } from "@/lib/numerals";
import { Card } from "@/components/ui/Card";
import { LinkButton } from "@/components/ui/LinkButton";
import { isSignedIn } from "@/lib/session";

/**
 * The home page — where the journey starts.
 *
 * This route used to be `redirect("/home")`, which meant the product had no
 * front door: a caregiver arriving for the first time landed on an empty
 * "Today" dashboard for a child that did not exist yet, with one button that
 * did nothing. A first screen has to answer "what is this, and what do I do
 * now", and those are the only two things on it.
 *
 * Rendered on the server so that the primary action is already correct on first
 * paint — "start" for a new caregiver, "continue" for one who is signed in.
 * There is no flash of the wrong button and no client-side auth check.
 */
export default async function HomePage() {
  const t = await getTranslations("landing");
  const tApp = await getTranslations("app");
  const tSkills = await getTranslations("skills");
  const signedIn = await isSignedIn();

  const steps = [
    { title: t("step1Title"), body: t("step1Body") },
    { title: t("step2Title"), body: t("step2Body") },
    { title: t("step3Title"), body: t("step3Body") },
  ];

  return (
    <div className="mx-auto max-w-[720px] px-5 py-10">
      <header className="text-center">
        <h1 className="text-4xl font-semibold text-primary">{tApp("title")}</h1>
        <p className="mt-3 text-lg text-ink">{t("tagline")}</p>
        <p className="mx-auto mt-4 max-w-[46ch] text-ink-muted">{t("lede")}</p>
      </header>

      <div className="mt-8 flex flex-col items-center gap-3">
        {signedIn ? (
          <LinkButton href="/home">{t("continue")}</LinkButton>
        ) : (
          <LinkButton href="/onboarding">{t("start")}</LinkButton>
        )}
        {signedIn ? null : (
          <LinkButton href="/onboarding" variant="ghost">
            {t("signIn")}
          </LinkButton>
        )}
      </div>

      <section className="mt-12" aria-labelledby="steps-heading">
        <h2 id="steps-heading" className="mb-4 text-xl font-semibold text-ink">
          {t("stepsTitle")}
        </h2>
        <ol className="space-y-4">
          {steps.map((step, index) => (
            <Card as="article" key={step.title}>
              <div className="flex items-start gap-4">
                {/* aria-hidden: the number is a visual ordinal. The <ol> already
                    tells a screen reader this is step N of 3. */}
                <span
                  aria-hidden
                  className="grid size-9 shrink-0 place-items-center rounded-pill bg-primary-soft font-semibold text-primary"
                >
                  {index + 1}
                </span>
                <div>
                  <h3 className="font-semibold text-ink">{step.title}</h3>
                  <p className="mt-1 text-ink-muted">{step.body}</p>
                </div>
              </div>
            </Card>
          ))}
        </ol>
      </section>

      {/* What the child actually does, shown rather than described.
          A caregiver deciding whether to sign up is deciding whether to hand
          their phone to their child, and three paragraphs of prose is a worse
          answer to that than six pictures of the thing itself. The drawings are
          the same ones the child taps in /play, by the same skill code. */}
      <section className="mt-12" aria-labelledby="worlds-heading">
        <h2 id="worlds-heading" className="mb-2 text-xl font-semibold text-ink">
          {t("worldsTitle")}
        </h2>
        <p className="mb-4 text-ink-muted">{t("worldsBody")}</p>
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {WORLDS.map(({ category, faceCode, tint, count }) => (
            <li
              key={category}
              data-testid={`landing-world-${category}`}
              className="flex flex-col items-center gap-2 rounded-lg p-4"
              style={{ backgroundColor: tint }}
            >
              <SkillArt code={faceCode} size={56} />
              <span className="font-semibold text-ink">{tSkills(`category.${category}`)}</span>
              <span className="text-sm text-ink-muted">{arabicDigits(count)}</span>
            </li>
          ))}
        </ul>
      </section>

      <nav aria-label={t("stepsTitle")} className="mt-10 flex flex-wrap justify-center gap-3">
        <LinkButton href="/play" variant="secondary">
          {t("playEntry")}
        </LinkButton>
        <LinkButton href="/console" variant="secondary">
          {t("consoleEntry")}
        </LinkButton>
      </nav>

      {/* Present on the first screen, not buried in a settings page. docs/06 §3
          treats this as copy the caregiver must have seen, not accepted. */}
      <p className="mt-10 border-t border-border pt-5 text-center text-sm text-ink-muted">
        {t("notMedical")}
      </p>
    </div>
  );
}
