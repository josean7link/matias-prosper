"use client";
import { ArrowUpRight, ArrowDownRight, Info } from "lucide-react";
import Link from "next/link";
import { fmtMoney, fmtNum, cn } from "@/lib/utils";

interface Props {
  label: string;
  value: string;
  delta?: number | null;          // -0.012 = -1.2%
  hint?: string;
  href?: string;
  loading?: boolean;
  tooltip?: string;               // explainer text (hover/focus)
}

export function KpiTile({ label, value, delta, hint, href, loading, tooltip }: Props) {
  const up = delta != null && delta >= 0;
  const testid = `kpi-${label.toLowerCase().replace(/[^a-z0-9]/g, "-")}`;
  const body = (
    <div
      className={cn(
        "prosper-card p-4 hover:shadow-card-hover transition-shadow h-full relative",
        href && "cursor-pointer",
      )}
      data-testid={testid}
    >
      <div className="flex items-center gap-1 text-[10px] uppercase tracking-[0.15em] font-mono text-fg-subtle">
        <span>{label}</span>
        {tooltip && (
          <span
            className="group/tip relative inline-flex"
            data-testid={`${testid}-tooltip-trigger`}
          >
            <Info
              size={11}
              className="text-fg-subtle/70 hover:text-fg cursor-help"
              tabIndex={0}
            />
            <span
              role="tooltip"
              className={cn(
                "pointer-events-none absolute left-1/2 top-full z-30 mt-1.5 -translate-x-1/2",
                "w-56 rounded border border-border bg-bg p-2 text-[10px] leading-snug",
                "font-mono normal-case tracking-normal text-fg-muted shadow-card-hover",
                "opacity-0 group-hover/tip:opacity-100 group-focus-within/tip:opacity-100",
                "transition-opacity",
              )}
              data-testid={`${testid}-tooltip`}
            >
              {tooltip}
            </span>
          </span>
        )}
      </div>
      {loading ? (
        <div className="mt-2 h-8 w-24 rounded bg-surface-hover animate-pulse" />
      ) : (
        <div className="font-display font-extrabold text-2xl text-fg tabular mt-1 leading-tight font-mono">
          {value}
        </div>
      )}
      <div className="mt-1.5 flex items-center gap-2 min-h-[16px]">
        {delta != null && !loading && (
          <span className={cn("inline-flex items-center gap-0.5 text-[11px] font-mono",
                              up ? "text-success" : "text-danger")}>
            {up ? <ArrowUpRight size={11} /> : <ArrowDownRight size={11} />}
            {(delta * 100).toFixed(2)}%
          </span>
        )}
        {hint && (
          <span className="text-[10px] text-fg-subtle font-mono">{hint}</span>
        )}
      </div>
    </div>
  );
  return href ? <Link href={href}>{body}</Link> : body;
}

export { fmtMoney, fmtNum };
