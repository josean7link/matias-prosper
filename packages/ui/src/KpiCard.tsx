import { ArrowUpRight, ArrowDownRight } from "lucide-react";

export interface KpiCardProps {
  label: string;
  value: string | number;
  delta?: number;        // 0.05 = +5%
  hint?: string;
  className?: string;
}

export function KpiCard({ label, value, delta, hint, className }: KpiCardProps) {
  const up = delta != null && delta >= 0;
  return (
    <div
      className={`prosper-card p-5 hover:shadow-card-hover transition-shadow ${className || ""}`}
      data-testid={`kpi-${label.toLowerCase().replace(/[^a-z0-9]/g, "-")}`}
    >
      <div className="text-[10px] uppercase tracking-[0.15em] font-mono text-fg-subtle mb-2">
        {label}
      </div>
      <div className="font-display font-extrabold text-3xl text-fg tabular leading-none">
        {value}
      </div>
      <div className="mt-2 flex items-center gap-2 min-h-[18px]">
        {delta != null ? (
          <span
            className={`inline-flex items-center gap-1 text-xs font-mono ${
              up ? "text-success" : "text-danger"
            }`}
          >
            {up ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}
            {(delta * 100).toFixed(2)}%
          </span>
        ) : null}
        {hint && (
          <span className="text-[11px] text-fg-subtle">{hint}</span>
        )}
      </div>
    </div>
  );
}
