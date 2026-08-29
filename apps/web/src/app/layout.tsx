import type { Metadata, Viewport } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getMessages } from "next-intl/server";
import type { ReactNode } from "react";

import { DIRECTION, LOCALE } from "@/i18n";
import "@/styles/globals.css";

export const metadata: Metadata = {
  title: "مِسك",
  description: "رفيقك في رحلة طفلك",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // Zoom is never disabled: caregivers using large text must be able to zoom.
  maximumScale: 5,
  themeColor: "#1F6F5C",
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  const messages = await getMessages();
  return (
    <html lang={LOCALE} dir={DIRECTION}>
      <body>
        <NextIntlClientProvider messages={messages}>{children}</NextIntlClientProvider>
      </body>
    </html>
  );
}
