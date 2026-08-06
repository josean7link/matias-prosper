"use client";
/**
 * Phase 04 — Background snapshot poll mounted at the /client/* layout
 * boundary. Its only purpose is to keep SWR's snapshot cache fresh
 * across every client surface (Dashboard, Withdraw, Positions, Activity)
 * AND surface the new-movement toast even when the user is not on the
 * Dashboard.
 *
 * Rendering: returns null. UI components (PendingDepositCard,
 * NewMovementBadge) live on the Dashboard intentionally — they belong
 * to the balances surface, not the chrome.
 */
import { usePortfolioSnapshot } from "@/lib/portfolio-snapshot";
import { useEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { fmtAmount } from "@/lib/portal-format";

export default function ClientPortfolioPoll() {
  const t = useTranslations("portfolio");
  const { isNewMovement, newestMovement } = usePortfolioSnapshot();
  const firedRef = useRef<string | null>(null);

  // Rail-aware toast. Mirrors `NewMovementBadge`'s logic so the user
  // gets a toast no matter which /client/* surface they are on.
  useEffect(() => {
    if (!isNewMovement || !newestMovement) return;
    if (firedRef.current === newestMovement.movement_id) return;
    firedRef.current = newestMovement.movement_id;
    const isArsa = newestMovement.asset === "arsa";
    const unit = isArsa ? "ARSa" : "USDC";
    const amount = Number(newestMovement.amount || 0);
    const copy = isArsa
      ? t("new_movement_toast_arsa", { amount: fmtAmount(amount, unit) })
      : t("new_movement_toast_usdc", { amount: fmtAmount(amount, unit) });
    toast(copy, { duration: 5_000 });
  }, [isNewMovement, newestMovement?.movement_id]);   // eslint-disable-line react-hooks/exhaustive-deps

  return null;
}
