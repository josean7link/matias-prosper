import { fmtNum } from "@/lib/format";
import { ArrowUpRight, Copy, Check } from "@phosphor-icons/react";
import { useState } from "react";
import { toast } from "sonner";
import { truncateAddr, stellarExplorer } from "@/lib/format";

export const PageHeader = ({ title, subtitle, actions, testId = "page-header" }) => (
  <div className="flex items-end justify-between mb-6 pb-5 border-b border-[var(--border)]" data-testid={testId}>
    <div>
      <h1 className="font-display font-black text-3xl md:text-4xl tracking-tight text-[var(--fg)]">{title}</h1>
      {subtitle && <p className="text-sm text-[var(--fg-muted)] mt-1">{subtitle}</p>}
    </div>
    {actions && <div className="flex gap-2">{actions}</div>}
  </div>
);

export const KpiCard = ({ label, value, sublabel, trend, testId }) => (
  <div className="kpi-tile prosper-card p-5" data-testid={testId}>
    <div className="text-[10px] uppercase tracking-[0.15em] text-[var(--fg-muted)] font-medium mb-2">{label}</div>
    <div className="font-mono text-2xl md:text-3xl font-semibold text-[var(--fg)] tabular-nums">{value}</div>
    {(sublabel || trend) && (
      <div className="flex items-center gap-2 mt-2 text-xs text-[var(--fg-muted)]">
        {trend !== undefined && trend !== null && (
          <span className="font-mono" style={{ color: trend > 0 ? "var(--success)" : "var(--danger)" }}>
            {trend > 0 ? "↑" : "↓"} {fmtNum(Math.abs(trend), 2)}%
          </span>
        )}
        {sublabel && <span>{sublabel}</span>}
      </div>
    )}
  </div>
);

// Map status -> CSS var so it automatically adapts to theme
const STATUS_VAR = {
  active: "--success", success: "--success", matched: "--success", confirmed: "--success",
  approved: "--success", delivered: "--success", resolved: "--success",
  pending: "--warning", under_review: "--warning", submitted: "--warning", retrying: "--warning",
  needs_info: "--warning", investigating: "--warning", escalated: "--warning", paused: "--warning",
  failed: "--danger", rejected: "--danger", revoked: "--danger", unmatched: "--danger",
  critical: "--danger", suspended: "--danger",
  warning: "--warning", info: "--primary",
  sandbox: "--warning", production: "--success",
};

export const StatusBadge = ({ value, testId }) => {
  const varName = STATUS_VAR[value] || "--fg-subtle";
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium" data-testid={testId || `status-${value}`}>
      <span className="status-dot" style={{ background: `var(${varName})` }} />
      <span className="uppercase tracking-wider text-[11px] text-[var(--fg)]">{String(value || "—").replace(/_/g, " ")}</span>
    </span>
  );
};

export const EnvPill = ({ env, testId = "env-pill" }) => (
  <span className="env-pill" data-env={env} data-testid={testId}>{env}</span>
);

export const StellarLink = ({ hash, testId = "stellar-link" }) => {
  if (!hash) return <span className="text-[var(--fg-subtle)]">—</span>;
  return (
    <a
      href={stellarExplorer(hash)}
      target="_blank"
      rel="noreferrer"
      className="inline-flex items-center gap-1 font-mono text-[12px] text-[var(--primary)] hover:underline"
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
      className="inline-flex items-center gap-2 font-mono text-xs px-2 py-1 rounded-md hover:bg-[var(--surface-hover)] transition-colors"
      onClick={handle}
      data-testid={testId}
    >
      <span>{truncateAddr(value, 10)}</span>
      {copied ? <Check size={12} style={{ color: "var(--success)" }} /> : <Copy size={12} className="text-[var(--fg-muted)]" />}
    </button>
  );
};

export const EmptyState = ({ title, message, action, testId = "empty-state" }) => (
  <div className="flex flex-col items-center justify-center py-20 text-center" data-testid={testId}>
    <div className="w-12 h-12 rounded-xl border border-[var(--border)] flex items-center justify-center mb-4 bg-[var(--surface)]">
      <span className="font-mono text-[var(--fg-subtle)] text-lg">∅</span>
    </div>
    <div className="text-[var(--fg)] font-medium mb-1">{title}</div>
    {message && <div className="text-sm text-[var(--fg-muted)] max-w-md">{message}</div>}
    {action && <div className="mt-4">{action}</div>}
  </div>
);

export const MetricBar = ({ children }) => (
  <div className="flex flex-wrap tight-grid border border-[var(--border)] rounded-xl overflow-hidden">{children}</div>
);

export const MetricCell = ({ label, value, testId }) => (
  <div className="px-5 py-4 flex-1 min-w-[160px]" data-testid={testId}>
    <div className="text-[10px] uppercase tracking-wider text-[var(--fg-muted)] mb-1">{label}</div>
    <div className="font-mono text-lg text-[var(--fg)] tabular-nums">{value}</div>
  </div>
);

// Kept for backwards-compatibility with earlier pages
export const DemoBanner = () => (
  <div className="demo-banner px-6 py-2 flex items-center gap-3 text-xs font-mono" data-testid="demo-banner">
    <span className="env-pill" data-env="sandbox">DEMO</span>
    <span>This environment is populated with demo data for exploration. All records are tagged is_demo=true.</span>
  </div>
);
