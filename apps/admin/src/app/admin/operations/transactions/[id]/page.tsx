"use client";
import Link from "next/link";
import { useState } from "react";
import { useParams } from "next/navigation";
import { PageHeader, Badge, StatusDot } from "@prosper/ui";
import {
  Check, X, Clock, Minus, RotateCcw, ChevronDown, ChevronRight,
  Copy, ExternalLink, ArrowLeft,
} from "lucide-react";
import { toast } from "sonner";
import {
  useLifecycle, retryStep,
  type LifecycleStep, type LifecycleStatus,
} from "@/lib/operations";
import { useMe } from "@/lib/me";
import { fmtMoney, cn } from "@/lib/utils";

const stepColor: Record<LifecycleStatus, { ring: string; bg: string; icon: string }> = {
  ok:      { ring: "ring-success", bg: "bg-success",   icon: "text-white" },
  error:   { ring: "ring-danger",  bg: "bg-danger",    icon: "text-white" },
  pending: { ring: "ring-warning", bg: "bg-warning",   icon: "text-white" },
  skipped: { ring: "ring-border",  bg: "bg-surface-hover", icon: "text-fg-subtle" },
};

function StepIcon({ status }: { status: LifecycleStatus }) {
  const props = { size: 13, strokeWidth: 3 };
  if (status === "ok")      return <Check  {...props} />;
  if (status === "error")   return <X      {...props} />;
  if (status === "pending") return <Clock  {...props} />;
  return <Minus {...props} />;
}

function fmtAbs(iso: string): string {
  return new Date(iso).toLocaleString("en-US", { hour12: false });
}
function fmtRel(iso: string): string {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export default function LifecyclePage() {
  const { id } = useParams<{ id: string }>();
  const { data, isLoading, mutate } = useLifecycle(id);
  const me = useMe();
  const isSuper = me.data?.user?.role === "super_admin";

  if (isLoading) {
    return <div className="prosper-card p-8 text-center text-fg-subtle">Loading…</div>;
  }
  if (!data) {
    return (
      <div className="prosper-card p-8 text-center text-fg-subtle"
            data-testid="lifecycle-not-found">
        Transaction not found.
        <Link href="/admin/operations/transactions"
              className="block mt-3 text-primary text-xs">← back to ledger</Link>
      </div>
    );
  }

  const tx = data.transaction;
  const lifecycle = data.lifecycle;
  const orgName = data.org?.commercial_name || data.org?.legal_name || tx.org_id;

  const handleRetry = async (stepId: string) => {
    try {
      await retryStep(tx.tx_id, stepId);
      toast.success(`Retry queued for ${stepId}`);
      mutate();
    } catch (err: any) {
      toast.error(err?.message || "Retry failed");
    }
  };

  return (
    <div data-testid="lifecycle-page">
      <PageHeader
        breadcrumbs={[
          { label: "Admin", href: "/admin" },
          { label: "Operations", href: "/admin/operations" },
          { label: "Ledger", href: "/admin/operations/transactions" },
          { label: tx.prosper_tx_id.slice(0, 14) + "…" },
        ]}
        kicker="Phase 3 · Lifecycle"
        title="Transaction lifecycle"
        actions={
          <Link href="/admin/operations/transactions"
                className="prosper-btn-ghost h-9 text-xs gap-1.5">
            <ArrowLeft size={13} /> Back
          </Link>
        }
      />

      {/* Header card */}
      <div className="prosper-card p-5 mb-6" data-testid="lifecycle-header">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="min-w-0">
            <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
              Prosper Tx ID
            </div>
            <div className="flex items-center gap-2 mt-0.5">
              <span className="font-display font-bold font-mono text-xl text-fg tabular">
                {tx.prosper_tx_id}
              </span>
              <button onClick={() => {
                navigator.clipboard.writeText(tx.prosper_tx_id);
                toast.success("Copied");
              }}
                data-testid="copy-prosper-tx-id"
                className="text-fg-subtle hover:text-primary">
                <Copy size={13} />
              </button>
            </div>
            <div className="mt-1 text-xs text-fg-muted">
              <Link href={`/admin/operations/by-client/${tx.org_id}`}
                    className="text-primary hover:underline">
                {orgName}
              </Link>
              <span className="mx-2">·</span>
              <Badge tone="auto" size="sm">{tx.type}</Badge>
            </div>
          </div>
          <div className="text-right">
            <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
              Amount
            </div>
            <div className="font-mono font-bold text-2xl text-fg tabular">
              {fmtMoney(tx.amount)} <span className="text-fg-subtle text-sm">{tx.asset}</span>
            </div>
            <div className="mt-1 inline-flex items-center gap-1.5 text-[11px] font-mono uppercase">
              <StatusDot color={tx.status === "confirmed" ? "green"
                                : tx.status === "failed" ? "red" : "yellow"} />
              {tx.status}
            </div>
          </div>
        </div>
      </div>

      {/* Step pills (mini horizontal) */}
      <div className="flex items-center gap-1.5 mb-5 overflow-x-auto pb-2"
           data-testid="step-pills">
        {lifecycle.map((s, i) => (
          <a key={s.step_id} href={`#step-${s.step_id}`}
             className={cn(
               "shrink-0 inline-flex items-center gap-1.5 h-7 px-2.5 rounded-full",
               "text-[10px] font-mono uppercase tracking-wider border",
               s.status === "ok"      && "border-success/30 text-success bg-success/5",
               s.status === "error"   && "border-danger/30 text-danger bg-danger/5",
               s.status === "pending" && "border-warning/30 text-warning bg-warning/5",
               s.status === "skipped" && "border-border text-fg-subtle bg-surface",
             )}
             data-testid={`pill-${s.step_id}`}>
            <StepIcon status={s.status} /> {i + 1}. {s.title}
          </a>
        ))}
      </div>

      {/* Vertical timeline */}
      <ol className="relative space-y-4" data-testid="lifecycle-timeline">
        {lifecycle.map((step, i) => (
          <StepCard key={step.step_id} step={step} index={i}
            isLast={i === lifecycle.length - 1}
            canRetry={isSuper && (step.status === "error" || step.status === "pending")}
            onRetry={() => handleRetry(step.step_id)} />
        ))}
      </ol>
    </div>
  );
}

function StepCard({ step, index, isLast, canRetry, onRetry }:
  { step: LifecycleStep; index: number; isLast: boolean;
    canRetry: boolean; onRetry: () => void }) {
  const [open, setOpen] = useState(false);
  const c = stepColor[step.status];

  return (
    <li id={`step-${step.step_id}`} className="relative pl-12"
        data-testid={`step-${step.step_id}`}>
      {/* Connector line */}
      {!isLast && (
        <div className="absolute left-[14px] top-7 bottom-[-16px] w-px bg-border" />
      )}
      {/* Step node */}
      <span
        className={cn("absolute left-0 top-0 w-[30px] h-[30px] rounded-full",
                       "flex items-center justify-center ring-4 ring-bg",
                       c.bg, c.icon)}
        data-testid={`step-icon-${step.step_id}`}>
        <StepIcon status={step.status} />
      </span>

      <div className="prosper-card p-4">
        <div className="flex items-start justify-between gap-2 flex-wrap">
          <div className="min-w-0">
            <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
              Step {index + 1} · {step.step_id}
            </div>
            <h3 className="font-display font-bold text-base text-fg mt-0.5">
              {step.title}
            </h3>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-mono text-fg-muted"
                  title={fmtAbs(step.timestamp)}>
              {fmtRel(step.timestamp)}
            </span>
            {canRetry && (
              <button onClick={onRetry}
                      data-testid={`retry-${step.step_id}`}
                      className="text-[10px] font-mono uppercase tracking-wider
                                 text-primary hover:bg-primary/10 px-2 h-7 rounded
                                 inline-flex items-center gap-1">
                <RotateCcw size={11} /> Retry
              </button>
            )}
          </div>
        </div>

        {/* Details rows */}
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
          {Object.entries(step.details).map(([k, v]) => (
            <DetailRow key={k} label={k} value={v} />
          ))}
        </dl>

        {/* Payload viewer */}
        {step.payload && (
          <div className="mt-3 border-t border-border pt-3">
            <button onClick={() => setOpen((o) => !o)}
                    data-testid={`payload-toggle-${step.step_id}`}
                    className="text-[10px] font-mono uppercase tracking-wider
                               text-fg-subtle hover:text-fg inline-flex items-center gap-1">
              {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
              {open ? "Hide" : "Show"} raw payload
            </button>
            {open && (
              <pre data-testid={`payload-${step.step_id}`}
                   className="mt-2 bg-surface border border-border rounded p-3
                              text-[10.5px] font-mono leading-snug overflow-auto
                              max-h-72 text-fg whitespace-pre">
{JSON.stringify(step.payload, null, 2)}
              </pre>
            )}
          </div>
        )}
      </div>
    </li>
  );
}

function DetailRow({ label, value }: { label: string; value: any }) {
  const isAddress = typeof value === "string" && /^G[A-Z0-9]{20,}/.test(value);
  const isHash    = typeof value === "string" && /^[a-f0-9]{40,}$/.test(value);
  const isUrl     = typeof value === "string" && value.startsWith("http");
  const display = isAddress || isHash
    ? `${(value as string).slice(0, 6)}…${(value as string).slice(-4)}`
    : isUrl ? "View →"
    : typeof value === "number" && value > 100 ? value.toLocaleString("en-US")
    : String(value);

  return (
    <>
      <dt className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle col-span-1">
        {label}
      </dt>
      <dd className="text-fg col-span-1 truncate" title={String(value)}>
        {isUrl ? (
          <a href={value} target="_blank" rel="noreferrer"
             className="text-primary hover:underline inline-flex items-center gap-1">
            View <ExternalLink size={10} />
          </a>
        ) : isAddress || isHash ? (
          <button onClick={() => { navigator.clipboard.writeText(value); toast.success("Copied"); }}
                  className="font-mono text-[11px] inline-flex items-center gap-1
                             hover:text-primary">
            {display} <Copy size={9} />
          </button>
        ) : (
          <span className="font-mono text-[11px]">{display}</span>
        )}
      </dd>
    </>
  );
}
