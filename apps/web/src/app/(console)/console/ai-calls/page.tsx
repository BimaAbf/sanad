import { Card } from "@/components/ui/Card";

/**
 * The ai_calls and guardrail_events explorer.
 *
 * Every row is already pseudonymised — names became {{CHILD}} before the
 * request left the gateway — so this view carries no identifiers and needs no
 * typed reason.
 */
export default function AiCallsPage() {
  return (
    <div data-testid="ai-calls">
      <h2 className="mb-4 text-lg font-semibold">نداءات الذكاء الاصطناعي</h2>
      <Card>
        <p className="text-ink-muted">كل سطر هنا متشال منه أي اسم قبل ما يتبعت.</p>
      </Card>
    </div>
  );
}
