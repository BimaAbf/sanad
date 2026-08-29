import { Card } from "@/components/ui/Card";

/**
 * The item-bank editor.
 *
 * Publishing is refused while any item in the bank is unreviewed (docs/09 P14).
 * That check is in the API — a console that merely hides the button would still
 * let a direct call through.
 */
export default function ItemsPage() {
  return (
    <div data-testid="items">
      <h2 className="mb-4 text-lg font-semibold">بنك الأسئلة</h2>
      <Card>
        <p className="text-ink-muted">
          النشر مرفوض طالما في سؤال واحد لسه مراجعوش حد بالاسم.
        </p>
      </Card>
    </div>
  );
}
