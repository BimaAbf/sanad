import { getTranslations } from "next-intl/server";

import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { getJourney } from "@/lib/queries";

/**
 * The journey view.
 *
 * The endpoint returns `insufficient_data` under three assessments and this
 * page renders the copy key it sends. The rule lives on the server
 * (`domain/views.py`) precisely so that this component cannot decide to draw a
 * two-point line anyway - a two-point "trend" in a developmental measure is
 * noise, and showing it to an anxious parent is telling them something untrue.
 *
 * Today the server always answers `insufficient_data`, because there is no
 * `assessments` table for `ProgressHistory.assessment_points` to read. That is
 * the correct screen for a product with no assessments in it, and it becomes a
 * real trend the moment the assessment engine gets persistence - with no change
 * to this file.
 */
export default async function JourneyPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const t = await getTranslations("journey");
  const { id } = await params;
  const journey = await getJourney(id);

  if (!journey || journey.status === "insufficient_data") {
    return <EmptyState title={t("title")} body={t("insufficient_data")} />;
  }

  return (
    <div data-testid="journey">
      <h1 className="mb-5 text-2xl font-semibold text-ink">{t("title")}</h1>
      <Card>
        <ol className="space-y-3">
          {journey.points.map((point) => (
            <li key={point.assessment_id} className="flex justify-between">
              <span>{point.completed_at}</span>
              <span className="font-semibold">{point.skills_mastered}</span>
            </li>
          ))}
        </ol>
      </Card>
    </div>
  );
}
