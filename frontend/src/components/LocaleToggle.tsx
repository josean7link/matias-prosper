"use client";
/**
 * <LocaleToggle> — pill EN / ES siempre visible en el header del shell.
 * Persiste la elección en cookie `prosper_locale` y refresca la página
 * para que Server Components reciban los messages del nuevo locale.
 */
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useTransition } from "react";

const LOCALE_COOKIE = "prosper_locale";
const LOCALES = ["en", "es"] as const;
type LocaleCode = (typeof LOCALES)[number];

function setLocaleCookie(loc: LocaleCode) {
  // 1 year, root path so the whole app sees it.
  const maxAge = 60 * 60 * 24 * 365;
  document.cookie = `${LOCALE_COOKIE}=${loc}; path=/; max-age=${maxAge}; samesite=lax`;
  try { localStorage.setItem(LOCALE_COOKIE, loc); } catch {}
}

export function LocaleToggle() {
  const t = useTranslations("language");
  const current = useLocale() as LocaleCode;
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  const onPick = (loc: LocaleCode) => {
    if (loc === current) return;
    setLocaleCookie(loc);
    startTransition(() => router.refresh());
  };

  return (
    <div
      className="inline-flex items-center rounded-full bg-surface-hover p-0.5"
      role="group"
      aria-label={t("switch_aria")}
      data-testid="locale-toggle"
    >
      {LOCALES.map((loc) => (
        <button
          key={loc}
          type="button"
          onClick={() => onPick(loc)}
          disabled={pending}
          aria-pressed={current === loc}
          data-testid={`locale-toggle-${loc}`}
          className={`h-7 px-2.5 rounded-full text-[10px] font-mono uppercase
                      tracking-wider transition disabled:opacity-50
                      ${current === loc
                        ? "bg-fg text-bg shadow-sm"
                        : "text-fg-muted hover:text-fg"}`}
        >
          {loc}
        </button>
      ))}
    </div>
  );
}
