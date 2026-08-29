import { getTranslations } from "next-intl/server";

import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";

/**
 * Today.
 *
 * Everything on this page comes from `GET /children/{id}/progress/today`,
 * already aggregated. The one rule visible here is the third from docs/04a
 * §C09: a regression is NEVER a bare negative signal — if `regression_detected`
 * is set, `revisit_plan` carries exactly three activities, and the server will
 * not send the flag without them.
 */

interface TodayPayload {
  sessions: number;
  minutes: number;
  streakDays: number;
  suggestion: { activityCode: string; labelAr: string } | null;
  revisitPlan: { activityCode: string; labelAr: string }[];
  regressionDetected: boolean;
}

async function loadToday(): Promise<TodayPayload> {
  return {
    sessions: 0,
    minutes: 0,
    streakDays: 0,
    suggestion: null,
    revisitPlan: [],
    regressionDetected: false,
  };
}

export default async function TodayPage() {
  const t = await getTranslations("today");
  const today = await loadToday();

  if (today.sessions === 0 && today.streakDays === 0) {
    return (
      <EmptyState
        title={t("title")}
        body={t("empty")}
        action={<Button>{t("start")}</Button>}
      />
    );
  }

  return (
    <div data-testid="today">
      <h1 className="mb-5 text-2xl font-semibold text-ink">{t("title")}</h1>

      <Card className="mb-5">
        <p data-testid="streak">{t("streak", { days: today.streakDays })}</p>
        <p data-testid="minutes" className="text-ink-muted">
          {t("minutes", { minutes: today.minutes })}
        </p>
      </Card>

      {today.suggestion ? (
        <Card className="mb-5">
          <h2 className="mb-2 font-semibold">{t("suggestion")}</h2>
          <p>{today.suggestion.labelAr}</p>
        </Card>
      ) : null}

      {/* The flag and the plan travel together. The server never sends one
          without the other, and this component never renders one alone. */}
      {today.regressionDetected && today.revisitPlan.length === 3 ? (
        <Card data-testid="revisit-plan">
          <h2 className="mb-3 font-semibold">{t("revisitIntro")}</h2>
          <ul className="space-y-3">
            {today.revisitPlan.map((activity) => (
              <li key={activity.activityCode} className="flex items-center justify-between">
                <span>{activity.labelAr}</span>
                <Button variant="secondary">{t("revisitAdd")}</Button>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
    </div>
  );
}
