import { getTranslations } from "next-intl/server";

import {
  SkillMapGrid,
  type MasteryState,
  type SkillCell,
} from "@/components/caregiver/SkillMapGrid";
import { EmptyState } from "@/components/ui/EmptyState";
import { getSkills, type SkillCard } from "@/lib/queries";

/**
 * The 88-skill map. An RSC: every number is aggregated server-side (docs/04a
 * C09), so this component receives render-ready data and does no arithmetic.
 */

const CATEGORY_ORDER = [
  "colors",
  "body_parts",
  "social",
  "household",
  "numbers",
  "letters",
] as const;

/**
 * The database and this component disagree about two state names, and the
 * mapping has to live somewhere explicit rather than inside a cast.
 *
 * `mastery_state` in migration 0001 is
 * not_started | introduced | practising | mastered | retained | lapsed.
 * `MasteryState` here is
 * not_started | emerging | practising | mastered | retained.
 *
 * So `introduced` and `lapsed` have no tile to render. They map to the nearest
 * state the caregiver-facing vocabulary has, which is also the reading docs/06
 * gives those words. The mismatch itself is a real defect in the pair and
 * belongs in REVIEW-QUEUE: one of the two vocabularies should move to meet the
 * other, and picking which one is a content decision, not a code one.
 */
const STATE_FROM_API: Record<string, MasteryState> = {
  not_started: "not_started",
  introduced: "emerging",
  emerging: "emerging",
  practising: "practising",
  lapsed: "practising",
  mastered: "mastered",
  retained: "retained",
};

function toCell(card: SkillCard): SkillCell {
  return {
    skillId: card.skill_id,
    code: card.code,
    labelAr: card.label_ar,
    state: STATE_FROM_API[card.state] ?? "not_started",
  };
}

export default async function SkillsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const t = await getTranslations("skills");
  const { id } = await params;
  const payload = await getSkills(id);

  // The API has already grouped these by category and counted them. Regrouping
  // here would be a second place where the grouping rule lives.
  const grouped: Record<string, SkillCell[]> = Object.fromEntries(
    Object.entries(payload?.by_category ?? {}).map(([category, cards]) => [
      category,
      cards.map(toCell),
    ]),
  );

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
