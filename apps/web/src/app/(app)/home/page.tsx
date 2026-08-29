import { useTranslations } from "next-intl";

export default function Home() {
  const t = useTranslations("app");
  return (
    <section>
      <h2 className="text-xl font-semibold">{t("tagline")}</h2>
      <p className="mt-4 text-base text-ink-muted">{t("placeholder")}</p>
    </section>
  );
}
