"use client";
/**
 * "Depósito en camino" card — rail-aware.
 *
 * Shows ONLY when the underlying snapshot reports a non-zero
 * `pending_detected` for the asset. Visually distinct from the
 * principal balance card; never sums into the operable balance.
 *
 * Copy NEVER mixes rails — ARSa template never says USDC and vice
 * versa.
 */
import { useTranslations } from "next-intl";
import { Clock3 } from "lucide-react";

import { fmtAmount } from "@/lib/portal-format";

export default function PendingDepositCard({
  asset, amount,
}: { asset: "arsa" | "usdc"; amount: number }) {
  const t = useTranslations("portfolio");
  if (!amount || amount <= 0) return null;
  const unit = asset === "arsa" ? "ARSa" : "USDC";
  return (
    <div
      data-testid={`pending-deposit-${asset}`}
      className="rounded-lg border border-dashed border-primary/40 bg-primary/5 px-3 py-2.5 flex items-center gap-3"
    >
      <Clock3 size={16} className="text-primary shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="text-[10px] font-mono uppercase tracking-wider text-primary">
          {asset === "arsa"
            ? t("deposit_in_transit_arsa_label")
            : t("deposit_in_transit_usdc_label")}
        </div>
        <div className="text-sm font-medium mt-0.5 tabular-nums">
          {fmtAmount(amount, unit)}
        </div>
      </div>
    </div>
  );
}
