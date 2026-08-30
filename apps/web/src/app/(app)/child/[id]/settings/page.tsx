import { getTranslations } from "next-intl/server";

import { Card } from "@/components/ui/Card";
import { MAX_WAIT_MS, MIN_WAIT_MS } from "@/lib/interaction";

/**
 * The accessibility profile.
 *
 * docs/09 P12: "plain-language questions, not jargon". So the wait-time control
 * asks "قد إيه نستنى طفلك يرد؟" rather than exposing a field called
 * `wait_time_ms` — the caregiver knows their child's pace; they do not know
 * ours.
 */
export default async function SettingsPage() {
  const t = await getTranslations("settings");
  return (
    <div data-testid="settings">
      <h1 className="mb-5 text-2xl font-semibold text-ink">{t("title")}</h1>
      <Card>
        <form className="space-y-6">
          <div>
            <label htmlFor="wait" className="mb-2 block font-semibold">
              {t("waitTime")}
            </label>
            <p className="mb-2 text-sm text-ink-muted">{t("waitTimeHelp")}</p>
            <input
              id="wait"
              name="wait"
              type="range"
              min={MIN_WAIT_MS}
              max={MAX_WAIT_MS}
              step={500}
              defaultValue={8000}
              className="w-full"
            />
          </div>
          <div>
            <label htmlFor="choices" className="mb-2 block font-semibold">
              {t("maxChoices")}
            </label>
            <input id="choices" name="choices" type="number" min={2} max={4} defaultValue={2} />
          </div>
          <div className="flex items-center gap-3">
            <input id="calm" name="calm" type="checkbox" />
            <label htmlFor="calm" className="font-semibold">
              {t("calmMode")}
            </label>
          </div>
          <p className="text-sm text-ink-muted">{t("calmModeHelp")}</p>
        </form>
      </Card>
    </div>
  );
}
