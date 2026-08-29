import { Card } from "@/components/ui/Card";

/**
 * Cost, per child, per day, per decision point — and per PROVIDER, which
 * docs/12 §Δ3 adds because the routing table sends different decision points to
 * different vendors and a single total would hide which one is expensive.
 */
export default function CostPage() {
  return (
    <div data-testid="cost">
      <h2 className="mb-4 text-lg font-semibold">التكلفة</h2>
      <Card>
        <p className="text-ink-muted">لسه مفيش استهلاك مسجّل.</p>
      </Card>
    </div>
  );
}
