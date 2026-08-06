/**
 * next-intl request-time config (Feb 2026).
 *
 * Locale resolution priority:
 *  1. `prosper_locale` cookie (explicit user choice — survives sessions)
 *  2. `Accept-Language` header (browser default)
 *  3. Fallback: English ("en") — the project's default per Feb 2026 spec.
 *
 * Supported locales are intentionally limited to {en, es}. Any extra value
 * received by the cookie gets clamped to "en" so we never break a render.
 */
import { cookies, headers } from "next/headers";
import { getRequestConfig } from "next-intl/server";

export const SUPPORTED_LOCALES = ["en", "es"] as const;
export type Locale = (typeof SUPPORTED_LOCALES)[number];
export const DEFAULT_LOCALE: Locale = "en";
export const LOCALE_COOKIE = "prosper_locale";

function pickFromAcceptLanguage(header: string | null | undefined): Locale {
  if (!header) return DEFAULT_LOCALE;
  // Match "es-AR,es;q=0.9,en-US;q=0.8" — we only care about the family.
  const families = header.split(",")
    .map((s) => s.trim().slice(0, 2).toLowerCase());
  for (const f of families) {
    if (f === "es") return "es";
    if (f === "en") return "en";
  }
  return DEFAULT_LOCALE;
}

export function resolveLocale(cookieValue: string | undefined,
                                  acceptLanguage: string | null): Locale {
  if (cookieValue && (SUPPORTED_LOCALES as readonly string[]).includes(cookieValue)) {
    return cookieValue as Locale;
  }
  return pickFromAcceptLanguage(acceptLanguage);
}

export default getRequestConfig(async () => {
  const c = (await cookies()).get(LOCALE_COOKIE)?.value;
  const acceptLang = (await headers()).get("accept-language");
  const locale = resolveLocale(c, acceptLang);
  const messages = (await import(`../../messages/${locale}.json`)).default;
  return { locale, messages };
});
