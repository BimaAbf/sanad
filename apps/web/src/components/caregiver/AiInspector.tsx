import { getTranslations } from "next-intl/server";

import { Card } from "@/components/ui/Card";
import type { Inspector, InspectorDecision } from "@/lib/queries";

/**
 * SHOW SANAD AI — why the session went the way it did.
 *
 * Every value here comes from a row: `ai_decisions` for the decisions,
 * `tutor_activities` for what was delivered, `attempts` for what the child did.
 * Nothing is recomputed for display and nothing is filled in — a field with no
 * stored value renders "غير متاح", because a plausible-looking number on the
 * one screen whose whole purpose is to be checkable would make it the least
 * trustworthy screen in the product.
 *
 * `decision_source` is shown as prominently as the decision itself. A
 * deterministic rule that happened to make a good choice is not a model
 * decision, and a demo that presented one as the other would be demonstrating
 * the wrong thing.
 *
 * Caregiver-visible, never child-facing. It is rendered on the report page,
 * which lives behind the caregiver's own authentication.
 */
export async function AiInspector({ inspector }: { inspector: Inspector | null }) {
  const t = await getTranslations("inspector");

  return (
    <Card data-testid="ai-inspector">
      <h2 className="text-xl font-semibold">{t("title")}</h2>
      <p className="mt-1 text-base text-ink-muted">{t("lede")}</p>

      {!inspector || inspector.decisions.length === 0 ? (
        <p className="mt-4 text-ink-muted" data-testid="inspector-empty">
          {t("empty")}
        </p>
      ) : (
        <>
          <p className="mt-4 text-base" data-testid="inspector-source">
            {t("source")}:{" "}
            {inspector.plan_source === "deterministic_fallback"
              ? t("sourceFallback")
              : t("sourceAi")}
          </p>
          <ol className="mt-4 space-y-4">
            {inspector.decisions.map((decision) => (
              <li key={decision.decision_id}>
                <Decision decision={decision} unavailable={t("unavailable")} labels={{
                  heading: t("decision", { ordinal: decision.ordinal }),
                  skill: t("skill"),
                  difficulty: t("difficulty"),
                  strategy: t("strategy"),
                  support: t("support"),
                  modality: t("modality"),
                  activityType: t("activityType"),
                  pKnown: t("pKnown"),
                  recent: t("recent"),
                  reasons: t("reasons"),
                  guardrails: t("guardrails"),
                  source: t("source"),
                  sourceAi: t("sourceAi"),
                  sourceFallback: t("sourceFallback"),
                  none: t("none"),
                }} />
              </li>
            ))}
          </ol>
        </>
      )}
    </Card>
  );
}

function Decision({
  decision,
  unavailable,
  labels,
}: {
  decision: InspectorDecision;
  unavailable: string;
  labels: Record<string, string>;
}) {
  /** A null is rendered as "unavailable", never as a zero or a blank. */
  const show = (value: string | number | null | undefined): string =>
    value === null || value === undefined || value === "" ? unavailable : String(value);

  return (
    <div
      className="rounded-md border border-primary-soft p-4"
      data-testid={`decision-${decision.ordinal}`}
      data-used-ai={String(decision.used_ai)}
    >
      <h3 className="font-semibold">{labels.heading}</h3>
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-2 text-base">
        <Row label={labels.skill ?? ""} value={show(decision.skill)} testId="decision-skill" />
        <Row label={labels.difficulty ?? ""} value={show(decision.difficulty)} />
        <Row label={labels.strategy ?? ""} value={show(decision.strategy)} testId="decision-strategy" />
        <Row label={labels.support ?? ""} value={show(decision.support_level)} />
        <Row label={labels.modality ?? ""} value={show(decision.modality)} />
        <Row label={labels.activityType ?? ""} value={show(decision.activity_type)} />
        <Row
          label={labels.pKnown ?? ""}
          // Four decimal places, because the point of showing it is that it
          // MOVED — and a rounded 0.3 to 0.3 looks like nothing happened.
          value={
            decision.p_known_at_decision === null
              ? unavailable
              : decision.p_known_at_decision.toFixed(4)
          }
          testId="decision-p-known"
        />
        <Row
          label={labels.source ?? ""}
          value={decision.used_ai ? (labels.sourceAi ?? "") : (labels.sourceFallback ?? "")}
          testId="decision-source"
        />
      </dl>

      <p className="mt-3 text-base">
        <span className="text-ink-muted">{labels.recent}: </span>
        {decision.recent_results.length > 0
          ? decision.recent_results.join(" · ")
          : unavailable}
      </p>

      <p className="mt-2 text-base" data-testid="decision-reasons">
        <span className="text-ink-muted">{labels.reasons}: </span>
        {decision.reason_codes.length > 0 ? decision.reason_codes.join(" · ") : unavailable}
      </p>

      {/* Shown even when empty. "The model asked for X and we did Y instead" is
          the most important line on this panel when it is non-empty, and a
          panel that only renders it sometimes teaches a reader to stop looking
          for it. */}
      <p className="mt-2 text-base" data-testid="decision-guardrails">
        <span className="text-ink-muted">{labels.guardrails}: </span>
        {decision.guardrail_actions.length > 0
          ? decision.guardrail_actions.join(" · ")
          : labels.none}
      </p>
    </div>
  );
}

function Row({
  label,
  value,
  testId,
}: {
  label: string;
  value: string;
  testId?: string;
}) {
  return (
    <>
      <dt className="text-ink-muted">{label}</dt>
      <dd data-testid={testId}>{value}</dd>
    </>
  );
}
