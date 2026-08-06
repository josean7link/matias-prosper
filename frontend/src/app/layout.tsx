import type { Metadata } from "next";
import { IBM_Plex_Sans, IBM_Plex_Mono, Chivo } from "next/font/google";
import { cookies, headers } from "next/headers";
import { NextIntlClientProvider } from "next-intl";
import { getMessages, getLocale } from "next-intl/server";
import "./globals.css";
import { Toaster } from "sonner";

const plexSans = IBM_Plex_Sans({
  subsets: ["latin"], weight: ["400","500","600","700"],
  variable: "--font-plex-sans", display: "swap",
});
const plexMono = IBM_Plex_Mono({
  subsets: ["latin"], weight: ["400","500","600"],
  variable: "--font-plex-mono", display: "swap",
});
const chivo = Chivo({
  subsets: ["latin"], weight: ["400","600","700","800","900"],
  variable: "--font-chivo", display: "swap",
});

export const metadata: Metadata = {
  title: "prosper · borderless on-chain financial services",
  description: "Regulated tokenized-yield platform on Stellar.",
  icons: {
    icon: [{ url: "/favicon.svg", type: "image/svg+xml" }],
    apple: [{ url: "/favicon.svg" }],
  },
};

export default async function RootLayout({ children }:
  { children: React.ReactNode }) {
  // SSR-safe theme: read cookie on server so the first paint matches the user's preference.
  const themeCookie = (await cookies()).get("prosper_theme")?.value;
  const theme = themeCookie === "dark" ? "dark" : "light";
  // i18n — locale & messages resolved via `src/i18n/request.ts` (cookie or
  // Accept-Language → defaults to "en"). NextIntlClientProvider injects
  // them into every Client Component.
  const locale = await getLocale();
  const messages = await getMessages();
  return (
    <html lang={locale} className={`${plexSans.variable} ${plexMono.variable} ${chivo.variable} ${theme}`}>
      <body className="font-sans antialiased">
        <NextIntlClientProvider locale={locale} messages={messages}>
          {children}
        </NextIntlClientProvider>
        <Toaster position="top-right" theme={theme as "light" | "dark"} />
      </body>
    </html>
  );
}
