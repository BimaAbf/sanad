import { useTranslations } from "next-intl";

export default function Play() {
  const t = useTranslations("play");
  return (
    <section>
      <h1 className="text-child font-semibold text-primary">{t("title")}</h1>
      <p className="mt-5 text-lg text-ink-muted">{t("placeholder")}</p>
    </section>
  );
}
