import { getTranslations } from "next-intl/server";

import { NextExerciseCard } from "@/components/caregiver/NextExerciseCard";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { LinkButton } from "@/components/ui/LinkButton";
import { getNextExercise, getToday } from "@/lib/queries";
import { getActiveChildId, isSignedIn } from "@/lib/session";

/**
 * Today.
 *
 * Everything on this page comes from `GET /children/{id}/progress/today`,
 * already aggregated. The one rule visible here is the third from docs/04a
 * C09: a regression is NEVER a bare negative signal - if `regression_detected`
 * is set, `revisit_plan` carries exactly three activities, and the server will
 * not send the flag without them.
 *
 * The three "nothing to show" cases are deliberately not collapsed into one
 * empty state, because they need three different next actions: not signed in,
 * signed in with no child, and a real child with no sessions yet.
 */
export default async function TodayPage() {
  const t = await getTranslations("today");
  const tLanding = await getTranslations("landing");

  if (!(await isSignedIn())) {
    return (
      <EmptyState
        title={t("title")}
        body={tLanding("lede")}
        action={<LinkButton href="/onboarding">{tLanding("start")}</LinkButton>}
      />
    );
  }

  const childId = await getActiveChildId();
  if (!childId) {
    return (
      <EmptyState
        title={t("title")}
        body={t("needsChild")}
        action={<LinkButton href="/onboarding">{t("addChild")}</LinkButton>}
      />
    );
  }

  // In parallel. The recommendation reads the retrieval index and the
  // deterministic candidate engine; today's totals read the rollups. Neither
  // needs the other, and serialising them would add a round trip to the first
  // screen a caregiver sees.
  const [today, recommendation] = await Promise.all([
    getToday(childId),
    getNextExercise(childId),
  ]);

  // Null is the documented "not configured" / "no access" case, not an error.
  // It renders the same instructional empty state a child with no sessions
  // gets, because the caregiver's next action is identical either way.
  if (!today || (today.sessions === 0 && today.streak_days === 0)) {
    return (
      <EmptyState
        title={t("title")}
        body={t("empty")}
        action={<LinkButton href="/play">{t("start")}</LinkButton>}
      />
    );
  }

  return (
    <div data-testid="today">
      <h1 className="mb-5 text-2xl font-semibold text-ink">{t("title")}</h1>

      <Card className="mb-5">
        <p data-testid="streak">{t("streak", { days: today.streak_days })}</p>
        <p data-testid="minutes" className="text-ink-muted">
          {t("minutes", { minutes: today.minutes })}
        </p>
        <p className="text-ink-muted">{t("attempts", { attempts: today.attempts })}</p>
      </Card>

      {/* This replaced the plain `today.suggestion` card. Both answer "what
          next"; the recommendation subsumes it -- same curriculum ordering,
          plus the composition rule (at most one new skill) and the retrieval-
          grounded reordering. Two cards answering one question would make a
          caregiver choose between two answers from the same product. */}
      <div className="mb-5">
        <NextExerciseCard childId={childId} recommendation={recommendation} />
      </div>

      {/* The flag and the plan travel together. The server never sends one
          without the other, and this component never renders one alone. */}
      {today.regression_detected && today.revisit_plan.length === 3 ? (
        <Card data-testid="revisit-plan">
          <h2 className="mb-3 font-semibold">{t("revisitIntro")}</h2>
          <ul className="space-y-3">
            {today.revisit_plan.map((activity) => (
              <li
                key={activity.activity_code}
                className="flex items-center justify-between gap-3"
              >
                <span>{activity.label_ar}</span>
                <LinkButton href="/play" variant="secondary">
                  {t("revisitAdd")}
                </LinkButton>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
    </div>
  );
}
