import { getTranslations } from "next-intl/server";

import { AiInspector } from "@/components/caregiver/AiInspector";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { LinkButton } from "@/components/ui/LinkButton";
import { apiFetchOrNull } from "@/lib/api";
import { getInspector, getRewards, getSessionReport } from "@/lib/queries";

/**
 * The caregiver's read of the last session, and why SANAD taught what it did.
 *
 * Every number is read back from the API. The narrative under them is built
 * from those same numbers by the server, which rejects any narrative containing
 * a number the session did not produce — so the prose and the table cannot
 * disagree, and `narrative_source` says which of the two wrote it.
 *
 * The AI inspector below is caregiver-visible and never child-facing. It is on
 * this page rather than behind a developer flag because "SANAD adapted" is a
 * claim, and a claim a parent cannot check is a claim they have to take on
 * trust.
 */

interface SessionHistory {
  child_id: string;
  sessions: {
    session_id: string;
    started_at: string;
    ended_at: string | null;
    activities_done: number;
    correct_count: number;
    stars: number;
  }[];
}

export default async function ChildReportPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const t = await getTranslations("session");
  const tr = await getTranslations("report");

  const history = await apiFetchOrNull<SessionHistory>(`/children/${id}/sessions`);
  const finished = history?.sessions.find((session) => session.ended_at !== null);

  if (!finished) {
    return (
      <EmptyState
        title={t("title")}
        body={t("empty")}
        action={<LinkButton href="/children">{tr("title")}</LinkButton>}
      />
    );
  }

  const [report, inspector, rewards] = await Promise.all([
    getSessionReport(finished.session_id),
    getInspector(finished.session_id),
    getRewards(id),
  ]);
  const facts = report?.facts;

  return (
    <div dir="rtl" data-testid="session-report">
      <h1 className="mb-1 text-2xl font-semibold">{t("title")}</h1>
      <p className="mb-5 text-ink-muted">{tr("notMedical")}</p>

      <Card className="mb-5">
        <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3">
          <Fact label={t("activities")} value={facts?.activities_completed ?? 0} testId="fact-activities" />
          <Fact label={t("independent")} value={facts?.independent_responses ?? 0} testId="fact-independent" />
          <Fact label={t("supported")} value={facts?.supported_responses ?? 0} testId="fact-supported" />
          <Fact label={t("minutes")} value={facts?.duration_minutes ?? 0} testId="fact-minutes" />
          <Fact label={t("stars")} value={rewards?.stars ?? 0} testId="fact-stars" />
        </dl>
      </Card>

      {report ? (
        <Card className="mb-5">
          {/* Whitespace preserved: the narrative is written as lines and the
              server counts them, so collapsing them here would make what a
              caregiver reads a different document from the one that was
              checked. */}
          <p data-testid="narrative" className="whitespace-pre-line text-lg leading-relaxed">
            {report.narrative_ar}
          </p>
          <p className="mt-3 text-base text-ink-muted" data-testid="narrative-source">
            {report.narrative_source}
          </p>
        </Card>
      ) : null}

      <div className="mb-5 grid gap-4 sm:grid-cols-2">
        <Card>
          <h2 className="mb-3 font-semibold">{t("wentWell")}</h2>
          <List items={facts?.went_well ?? []} empty={t("none")} testId="went-well" />
        </Card>
        <Card>
          <h2 className="mb-3 font-semibold">{t("needsPractice")}</h2>
          <List items={facts?.needs_practice ?? []} empty={t("none")} testId="needs-practice" />
        </Card>
      </div>

      <Card className="mb-5">
        <h2 className="mb-3 font-semibold">{t("changes")}</h2>
        {facts && facts.mastery_changes.length > 0 ? (
          <ul className="space-y-2" data-testid="mastery-changes">
            {facts.mastery_changes.map((change, index) => (
              <li key={`${change.skill_code}-${index}`}>
                {change.skill_label_ar}: {change.from_state} → {change.to_state}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-ink-muted">{t("none")}</p>
        )}
      </Card>

      <AiInspector inspector={inspector} />
    </div>
  );
}

function Fact({
  label,
  value,
  testId,
}: {
  label: string;
  value: number;
  testId: string;
}) {
  return (
    <div>
      <dt className="text-base text-ink-muted">{label}</dt>
      <dd className="text-2xl font-semibold" data-testid={testId}>
        {value}
      </dd>
    </div>
  );
}

function List({
  items,
  empty,
  testId,
}: {
  items: string[];
  empty: string;
  testId: string;
}) {
  if (items.length === 0) return <p className="text-ink-muted">{empty}</p>;
  return (
    <ul className="space-y-2" data-testid={testId}>
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}
