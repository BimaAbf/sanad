import { getTranslations } from "next-intl/server";

import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { LinkButton } from "@/components/ui/LinkButton";
import { getMe } from "@/lib/queries";

export default async function ChildrenPage() {
  const t = await getTranslations("children");
  const me = await getMe();
  const children = me?.children ?? [];
  if (!me) {
    return <EmptyState title={t("title")} body={t("signedOut")} action={<LinkButton href="/onboarding">{t("signIn")}</LinkButton>} />;
  }
  return (
    <div dir="rtl" data-testid="children-page">
      <div className="mb-6 flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">{t("title")}</h1>
          <p className="mt-1 text-ink-muted">{t("subtitle")}</p>
        </div>
        <LinkButton href="/onboarding">{t("add")}</LinkButton>
      </div>
      {children.length === 0 ? (
        <EmptyState title={t("emptyTitle")} body={t("emptyBody")} action={<LinkButton href="/onboarding">{t("add")}</LinkButton>} />
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2">
          {children.map((child) => (
            <li key={child.id}>
              <Card>
                <h2 className="text-xl font-semibold">{child.display_name}</h2>
                <p className="mt-2 text-ink-muted">{t("role", { role: child.role })}</p>
                <LinkButton className="mt-5" href={`/child/${child.id}/coach`}>{t("open")}</LinkButton>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
