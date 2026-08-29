import { getRequestConfig } from "next-intl/server";

/**
 * Misk ships one locale: Egyptian colloquial Arabic. There is no locale prefix
 * in the URL and no language switcher — adding either would imply an English
 * product exists, and it does not.
 */
export const LOCALE = "ar-EG" as const;
export const DIRECTION = "rtl" as const;

export default getRequestConfig(async () => ({
  locale: LOCALE,
  messages: (await import("./messages/ar-EG.json")).default,
  timeZone: "Africa/Cairo",
  now: new Date(),
}));
