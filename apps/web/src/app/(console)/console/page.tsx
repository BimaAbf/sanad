import { useTranslations } from "next-intl";

export default function Console() {
  const t = useTranslations("console");
  return (
    <section>
      <h2 className="text-xl font-semibold">{t("title")}</h2>
      <p className="mt-4 text-base text-ink-muted">{t("placeholder")}</p>
    </section>
  );
}
