"use client";
/**
 * "Nuevo movimiento" subtle indicator. Auto-hides via the
 * `isNewMovement` flag managed by `usePortfolioSnapshot`. Also fires
 * a single toast on each transition (rail-aware: the copy mentions
 * the asset that just moved, never a generic blend).
 */
import { useEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { Sparkles } from "lucide-react";

import { fmtAmount } from "@/lib/portal-format";
import type { SnapshotMovement } from "@/lib/portfolio-snapshot";

export default function NewMovementBadge({
  show, newestMovement,
}: { show: boolean; newestMovement: SnapshotMovement | null }) {
  const t = useTranslations("portfolio");
  const firedRef = useRef<string | null>(null);

  useEffect(() => {
    if (!show || !newestMovement) return;
    // Dedupe: avoid double toasting for the same movement_id (e.g.
    // re-render churn).
    if (firedRef.current === newestMovement.movement_id) return;
    firedRef.current = newestMovement.movement_id;

    const isArsa = newestMovement.asset === "arsa";
    const unit = isArsa ? "ARSa" : "USDC";
    const amount = Number(newestMovement.amount || 0);
    const copy = isArsa
      ? t("new_movement_toast_arsa", { amount: fmtAmount(amount, unit) })
      : t("new_movement_toast_usdc", { amount: fmtAmount(amount, unit) });
    toast(copy, { duration: 5_000 });
  }, [show, newestMovement?.movement_id]);   // eslint-disable-line react-hooks/exhaustive-deps

  if (!show) return null;
  return (
    <span
      data-testid="new-movement-badge"
      className="inline-flex items-center gap-1.5 px-2 py-1 rounded-full bg-primary/10 text-primary text-[10px] font-mono uppercase tracking-wider animate-fade-in"
    >
      <Sparkles size={11} />
      {t("new_movement_badge")}
    </span>
  );
}
