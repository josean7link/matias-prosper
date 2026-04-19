import { cn } from "@/lib/utils";
import { fmtNum, fmtCompact, truncateAddr, stellarExplorer } from "@/lib/format";
import { ArrowUpRight, Copy, Check } from "@phosphor-icons/react";
import { useState } from "react";
import { toast } from "sonner";

export const PageHeader = ({ title, subtitle, actions, testId = "page-header" }) => (
  <div className="flex items-end justify-between mb-6 pb-4 border-b border-[#1a1a1a]" data-testid={testId}>
    <div>
      <h1 className="font-display font-black text-3xl md:text-4xl tracking-tight text-white">{title}</h1>
      {subtitle && <p className="text-sm text-[#888] mt-1">{subtitle}</p>}
    </div>
    {actions && <div className="flex gap-2">{actions}</div>}
  </div>
);

export const KpiCard = ({ label, value, sublabel, trend, testId }) => (
  <div className="kpi-tile prosper-card p-5" data-testid={testId}>
    <div className="text-[10px] uppercase tracking-[0.15em] text-[#888] font-medium mb-2">{label}</div>
    <div className="font-mono text-2xl md:text-3xl font-semibold text-white tabular-nums">{value}</div>
    {(sublabel || trend) && (
      <div className="flex items-center gap-2 mt-2 text-xs text-[#888]">
        {trend && (
          <span className={cn("font-mono", trend > 0 ? "text-[#00C853]" : "text-[#FF3D00]")}>
            {trend > 0 ? "↑" : "↓"} {fmtNum(Math.abs(trend), 2)}%
          </span>
        )}
        {sublabel && <span>{sublabel}</span>}
      </div>
    )}
  </div>
);

const STATUS_COLORS = {
  active: "#00C853", success: "#00C853", matched: "#00C853", confirmed: "#00C853",
  approved: "#00C853", delivered: "#00C853", resolved: "#00C853",
  pending: "#FFAB00", under_review: "#FFAB00", submitted: "#FFAB00", retrying: "#FFAB00",
  needs_info: "#FFAB00", investigating: "#FFAB00", escalated: "#FFAB00", paused: "#FFAB00",
  failed: "#FF3D00", rejected: "#FF3D00", revoked: "#FF3D00", unmatched: "#FF3D00",
  critical: "#FF3D00", suspended: "#FF3D00",
  warning: "#FFAB00", info: "#0066FF",
  sandbox: "#FFAB00", production: "#00C853",
};

export const StatusBadge = ({ value, testId }) => {
  const color = STATUS_COLORS[value] || "#888";
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-white" data-testid={testId || `status-${value}`}>
      <span className="status-dot" style={{ background: color }} />
      <span className="uppercase tracking-wider text-[11px] text-[#ccc]">{String(value || "—").replace(/_/g, " ")}</span>
    </span>
  );
};

export const EnvPill = ({ env, testId = "env-pill" }) => (
  <span className="env-pill" data-env={env} data-testid={testId}>{env}</span>
);

export const DemoBanner = () => (
  <div className="demo-banner px-6 py-2 flex items-center gap-3 text-xs" data-testid="demo-banner">
    <span className="env-pill" data-env="sandbox">DEMO</span>
    <span className="text-[#FFAB00] font-mono">
      This environment is populated with demo data for exploration. All records are tagged is_demo=true.
    </span>
  </div>
);

export const StellarLink = ({ hash, testId = "stellar-link" }) => {
  if (!hash) return <span className="text-[#555]">—</span>;
  return (
    <a
      href={stellarExplorer(hash)}
      target="_blank"
      rel="noreferrer"
      className="inline-flex items-center gap-1 font-mono text-[12px] text-[#0066FF] hover:underline"
      data-testid={testId}
    >
      {truncateAddr(hash, 6)}
      <ArrowUpRight size={12} weight="bold" />
    </a>
  );
};

export const CopyField = ({ value, testId = "copy-field" }) => {
  const [copied, setCopied] = useState(false);
  const handle = () => {
    navigator.clipboard.writeText(value);
    setCopied(true);
    toast.success("Copied to clipboard");
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <button
      className="inline-flex items-center gap-2 font-mono text-xs px-2 py-1 rounded-sm hover:bg-[#111] transition-colors"
      onClick={handle}
      data-testid={testId}
    >
      <span>{truncateAddr(value, 10)}</span>
      {copied ? <Check size={12} className="text-[#00C853]" /> : <Copy size={12} className="text-[#888]" />}
    </button>
  );
};

export const EmptyState = ({ title, message, action, testId = "empty-state" }) => (
  <div className="flex flex-col items-center justify-center py-20 text-center" data-testid={testId}>
    <div className="w-12 h-12 rounded-sm border border-[#222] flex items-center justify-center mb-4 bg-[#0a0a0a]">
      <span className="font-mono text-[#555] text-lg">∅</span>
    </div>
    <div className="text-white font-medium mb-1">{title}</div>
    {message && <div className="text-sm text-[#888] max-w-md">{message}</div>}
    {action && <div className="mt-4">{action}</div>}
  </div>
);

export const MetricBar = ({ children }) => (
  <div className="flex flex-wrap gap-0 tight-grid border border-[#1a1a1a]">{children}</div>
);

export const MetricCell = ({ label, value, testId }) => (
  <div className="px-5 py-4 flex-1 min-w-[160px]" data-testid={testId}>
    <div className="text-[10px] uppercase tracking-wider text-[#888] mb-1">{label}</div>
    <div className="font-mono text-lg text-white tabular-nums">{value}</div>
  </div>
);
