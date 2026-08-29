import { getTranslations } from "next-intl/server";

import { CONSOLE_ROUTES } from "@/lib/console-access";

export default async function ConsoleHome() {
  const t = await getTranslations("console");
  return (
    <div data-testid="console-home">
      <h2 className="mb-4 text-lg font-semibold">{t("title")}</h2>
      <ul className="grid gap-3 sm:grid-cols-2">
        {CONSOLE_ROUTES.map((route) => (
          <li key={route} className="rounded-md border border-border p-4">
            <a href={`/console/${route}`} className="text-primary underline">
              {route}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
