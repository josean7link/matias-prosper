"use client";
import { useTranslations } from "next-intl";
import { RefreshCw } from "lucide-react";

export function RefreshButton({ onClick }: { onClick?: () => void } = {}) {
  const t = useTranslations("common");
  return (
    <button
      onClick={onClick ?? (() => window.location.reload())}
      className="prosper-btn-ghost h-9 text-xs gap-1.5"
      data-testid="page-action-refresh"
      aria-label={t("refresh")}
    >
      <RefreshCw size={13} />
      {t("refresh")}
    </button>
  );
}
