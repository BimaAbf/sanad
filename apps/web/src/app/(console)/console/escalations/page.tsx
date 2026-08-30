import { Card } from "@/components/ui/Card";

/**
 * The escalation queue, sorted by SLA.
 *
 * Every row here is a child's own words that a guardrail flagged. Opening one
 * is an access to an identified child record, so it requires a typed reason and
 * writes an audit_log row — enforced by the API, surfaced here so a clinician
 * knows their reason is recorded rather than discovering it later.
 */
interface Escalation {
  id: string;
  slaDueAt: string;
  status: "open" | "acknowledged" | "responded" | "resolved" | "dismissed";
}

async function loadQueue(): Promise<Escalation[]> {
  return [];
}

export default async function EscalationsPage() {
  const queue = await loadQueue();
  return (
    <div data-testid="escalations">
      <h2 className="mb-4 text-lg font-semibold">الحالات المحوّلة</h2>
      {queue.length === 0 ? (
        <Card>
          <p className="text-ink-muted">مفيش حالات مفتوحة دلوقتي.</p>
        </Card>
      ) : (
        <ol className="space-y-3">
          {queue.map((row) => (
            <li key={row.id} data-testid={`escalation-${row.id}`}>
              <Card>
                <div className="flex justify-between">
                  <span>{row.id}</span>
                  <span className="text-ink-muted">{row.slaDueAt}</span>
                </div>
              </Card>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
