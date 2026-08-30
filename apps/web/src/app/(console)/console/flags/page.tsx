import { Card } from "@/components/ui/Card";

/**
 * Feature flags.
 *
 * docs/09 P14: a toggle takes effect in the API within 30 seconds without a
 * deploy, and every change is audit-logged. The 30 seconds is the flag cache
 * TTL in the API — this page only writes; it does not hold the guarantee.
 */
export default function FlagsPage() {
  return (
    <div data-testid="flags">
      <h2 className="mb-4 text-lg font-semibold">المفاتيح</h2>
      <Card>
        <p className="text-ink-muted">
          كل تغيير هنا بيتسجّل باسمك وبيوصل الـ API في أقل من ٣٠ ثانية.
        </p>
      </Card>
    </div>
  );
}
