"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, Bell, ClipboardCheck, FileCheck2, GitMerge, Webhook } from "lucide-react";
import { Badge, StatusDot } from "@prosper/ui";
import { cn } from "@/lib/utils";
import type { OpsQueue, OpsQueueGroup, OpsQueueItem } from "@/lib/dashboard";

type Variant = "danger" | "warning" | "primary" | "muted";

interface RowProps {
  icon: React.ReactNode;
  label: string;
  group: OpsQueueGroup;
  href: string;
  variant?: Variant;
  flash?: boolean;
  itemLabel?: (item: OpsQueueItem) => string;
}

const variantBadge: Record<Variant, "danger" | "warning" | "primary" | "default"> = {
  danger: "danger",
  warning: "warning",
  primary: "primary",
  muted: "default",
};

function Row({ icon, label, group, href, variant = "primary", flash, itemLabel }: RowProps) {
  const isEmpty = group.count === 0;
  return (
    <Link
      href={href}
      data-testid={`ops-row-${label.toLowerCase().replace(/[^a-z0-9]/g, "-")}`}
      className={cn(
        "group block px-4 py-3 border-b border-border last:border-0",
        "hover:bg-surface-hover transition-colors",
        flash && "ops-flash",
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5 min-w-0">
          <span className={cn(
            "inline-flex w-7 h-7 items-center justify-center rounded",
            isEmpty ? "bg-surface-hover text-fg-subtle" : "bg-[color-mix(in_srgb,#2B6BFF_12%,transparent)] text-primary",
          )}>
            {icon}
          </span>
          <div className="min-w-0">
            <div className="text-xs font-mono uppercase tracking-wider text-fg-muted">{label}</div>
            <div className="font-display font-bold text-lg text-fg font-mono leading-none mt-0.5">
              {group.count}
            </div>
          </div>
        </div>
        <ArrowUpRight size={14} className="text-fg-subtle group-hover:text-fg transition-colors" />
      </div>

      {group.items.length > 0 && (
        <ul className="mt-2.5 pl-9 space-y-1">
          {group.items.slice(0, 3).map((it, i) => (
            <li key={i} className="text-[11px] text-fg-subtle font-mono truncate flex items-center gap-2">
              <span className="truncate">{itemLabel ? itemLabel(it) : (it.commercial_name || it.type || it.org_id || "—")}</span>
              {it.severity && <Badge tone="auto" size="sm">{it.severity}</Badge>}
              {it.kyb_status && !it.severity && <Badge tone={variantBadge[variant]} size="sm">{it.kyb_status}</Badge>}
            </li>
          ))}
        </ul>
      )}
    </Link>
  );
}

export function OpsQueuePanel({ data, loading }: { data: OpsQueue | undefined; loading?: boolean }) {
  // Flash highlight when total count changes
  const total = data
    ? data.approvals.count + data.kyb.count + data.alerts.count + data.webhook_failing.count + data.reconciliation.count
    : 0;
  const [prevTotal, setPrevTotal] = useState<number | null>(null);
  const [flashKey, setFlashKey] = useState(0);
  useEffect(() => {
    if (!data) return;
    if (prevTotal != null && total !== prevTotal) setFlashKey((k) => k + 1);
    setPrevTotal(total);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [total]);

  const flashing = flashKey > 0;

  return (
    <aside
      className="prosper-card overflow-hidden"
      data-testid="ops-queue-panel"
    >
      <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-surface">
        <div>
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">Live · 30s</div>
          <h3 className="font-display font-bold text-sm text-fg mt-0.5">Operations Queue</h3>
        </div>
        <StatusDot color={total > 0 ? "yellow" : "green"} pulse={total > 0} />
      </div>

      {loading && !data ? (
        <div className="p-4 space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-12 rounded bg-surface-hover animate-pulse" />
          ))}
        </div>
      ) : data ? (
        <div key={flashKey}>
          <Row
            icon={<ClipboardCheck size={14} />}
            label="Approvals"
            group={data.approvals}
            href="/admin/operations"
            variant="primary"
            flash={flashing}
            itemLabel={(it) => `${it.type || "approval"} · ${it.org_id ?? ""}`}
          />
          <Row
            icon={<FileCheck2 size={14} />}
            label="KYB pending"
            group={data.kyb}
            href="/admin/compliance"
            variant="warning"
            flash={flashing}
          />
          <Row
            icon={<Bell size={14} />}
            label="Open alerts"
            group={data.alerts}
            href="/admin/operations"
            variant="danger"
            flash={flashing}
            itemLabel={(it) => it.type ?? it.alert_id ?? "alert"}
          />
          <Row
            icon={<Webhook size={14} />}
            label="Webhooks failing"
            group={data.webhook_failing}
            href="/admin/operations"
            variant="danger"
          />
          <Row
            icon={<GitMerge size={14} />}
            label="Reconciliation"
            group={data.reconciliation}
            href="/admin/operations"
            variant="warning"
          />
        </div>
      ) : null}

      {data && (
        <div className="px-4 py-2 border-t border-border bg-surface text-[10px] font-mono text-fg-subtle uppercase tracking-wider">
          Last refresh · {new Date(data.generated_at).toLocaleTimeString("en-US", { hour12: false })}
        </div>
      )}

      <style jsx>{`
        :global(.ops-flash) {
          animation: opsFlash 1.2s ease-out;
        }
        @keyframes opsFlash {
          0%   { background: color-mix(in srgb, #E07B00 22%, transparent); }
          100% { background: transparent; }
        }
      `}</style>
    </aside>
  );
}
