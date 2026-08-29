import { getTranslations } from "next-intl/server";

import { SkillMapGrid, type MasteryState, type SkillCell } from "@/components/caregiver/SkillMapGrid";
import { EmptyState } from "@/components/ui/EmptyState";

/**
 * The 88-skill map. An RSC: every number is aggregated server-side (docs/04a
 * §C09), so this component receives render-ready data and does no arithmetic.
 */

const CATEGORY_ORDER = [
  "colors",
  "body_parts",
  "social",
  "household",
  "numbers",
  "letters",
] as const;

async function loadSkills(): Promise<Record<string, SkillCell[]>> {
  // Wired to GET /children/{id}/progress/skills. Empty until the API is
  // reachable, which renders the instructional empty state rather than a
  // half-populated grid.
  return {};
}

export default async function SkillsPage() {
  const t = await getTranslations("skills");
  const grouped = await loadSkills();

  const stateLabels: Record<MasteryState, string> = {
    not_started: t("state.not_started"),
    emerging: t("state.emerging"),
    practising: t("state.practising"),
    mastered: t("state.mastered"),
    retained: t("state.retained"),
  };

  const total = Object.values(grouped).reduce((sum, list) => sum + list.length, 0);
  if (total === 0) {
    return <EmptyState title={t("title")} body={t("empty", { child: "" })} />;
  }

  return (
    <div data-testid="skills-map">
      <h1 className="mb-5 text-2xl font-semibold text-ink">{t("title")}</h1>
      {CATEGORY_ORDER.filter((category) => grouped[category]?.length).map((category) => (
        <SkillMapGrid
          key={category}
          category={category}
          categoryLabel={t(`category.${category}`)}
          skills={grouped[category]!}
          stateLabels={stateLabels}
        />
      ))}
    </div>
  );
}
