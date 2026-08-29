import { getTranslations } from "next-intl/server";

import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";

/**
 * The journey view.
 *
 * The endpoint returns `insufficient_data` under three assessments and this
 * page renders the copy key it sends. The rule lives on the server
 * (`domain/views.py`) precisely so that this component cannot decide to draw a
 * two-point line anyway — a two-point "trend" in a developmental measure is
 * noise, and showing it to an anxious parent is telling them something untrue.
 */

interface JourneyPayload {
  status: "ok" | "insufficient_data";
  points: { assessmentId: string; completedAt: string; skillsMastered: number }[];
  copyKey: string;
}

async function loadJourney(): Promise<JourneyPayload> {
  return { status: "insufficient_data", points: [], copyKey: "journey.insufficient_data" };
}

export default async function JourneyPage() {
  const t = await getTranslations("journey");
  const journey = await loadJourney();

  if (journey.status === "insufficient_data") {
    return (
      <EmptyState
        title={t("title")}
        body={t("insufficient_data")}
      />
    );
  }

  return (
    <div data-testid="journey">
      <h1 className="mb-5 text-2xl font-semibold text-ink">{t("title")}</h1>
      <Card>
        <ol className="space-y-3">
          {journey.points.map((point) => (
            <li key={point.assessmentId} className="flex justify-between">
              <span>{point.completedAt}</span>
              <span className="font-semibold">{point.skillsMastered}</span>
            </li>
          ))}
        </ol>
      </Card>
    </div>
  );
}
