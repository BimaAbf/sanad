import { getTranslations } from "next-intl/server";

import { Card } from "@/components/ui/Card";
import { LinkButton } from "@/components/ui/LinkButton";
import type { NextExercise } from "@/lib/queries";

/**
 * The next best exercise.
 *
 * What is deliberately NOT on this card: the `source` field, which says whether
 * the model or the deterministic engine produced the ordering. It is on the API
 * response for the clinician console and for anyone reviewing a recommendation
 * after the fact — but a caregiver being told "an AI chose this" and "a rule
 * chose this" on different days would reasonably trust the two differently,
 * when in fact both orderings were approved by the same clinical rule. What
 * they see is the activity and one sentence about why.
 *
 * `kind` is shown as a small Arabic chip because it is the honest reason the
 * activity is on the list at all — a review, a lapse, something new, or a
 * guaranteed win — and it is the part a caregiver can act on.
 */

const KIND_KEY: Record<string, string> = {
  lapsed: "kindLapsed",
  due: "kindDue",
  new: "kindNew",
  confidence: "kindConfidence",
};

export async function NextExerciseCard({
  childId,
  recommendation,
}: {
  childId: string;
  recommendation: NextExercise | null;
}) {
  const t = await getTranslations("recommendation");

  if (recommendation === null) {
    // Not an error. A child with nothing eligible has either finished
    // everything available or has not started, and both are real screens.
    return (
      <Card data-testid="next-exercise-empty">
        <h2 className="mb-2 font-semibold text-ink">{t("title")}</h2>
        <p className="text-ink-muted">{t("empty")}</p>
      </Card>
    );
  }

  const kindKey = KIND_KEY[recommendation.kind];

  return (
    <Card data-testid="next-exercise" data-kind={recommendation.kind}>
      <h2 className="mb-2 font-semibold text-ink">{t("title")}</h2>
      <p className="text-xl font-semibold text-ink">{recommendation.label_ar}</p>
      {kindKey ? (
        <span className="mt-2 inline-block rounded-pill bg-primary-soft px-3 py-1 text-sm text-primary">
          {t(kindKey)}
        </span>
      ) : null}
      <p className="mt-3 text-ink-muted">{recommendation.reason_ar}</p>
      <LinkButton href={`/play?child=${childId}&skill=${recommendation.skill_code}`} className="mt-4">
        {t("start")}
      </LinkButton>
    </Card>
  );
}
