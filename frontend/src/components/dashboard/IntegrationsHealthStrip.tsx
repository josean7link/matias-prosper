"use client";
import useSWR from "swr";
import Link from "next/link";
import {
  ShieldCheck, ScrollText, Mail, Coins, ArrowDownUp, Bell, CreditCard, Plug,
  RefreshCw, Activity,
} from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

interface HealthItem {
  provider: string; name: string; category: string;
  status: "active" | "partial" | "missing";
  mode: "sandbox" | "live";
  supports_test: boolean;
  health: "ok" | "degraded" | "missing";
  last_test: { ok?: boolean; message?: string;
               tested_at?: string; status_code?: number | null } | null;
  ran_now: boolean;
  required_filled: number; required_total: number;
}
interface HealthResponse {
  items: HealthItem[]; total: number;
  counts: { ok: number; degraded: number; missing: number };
  generated_at: string; stale_after_minutes: number;
}

const ICON: Record<string, React.ComponentType<{ size?: number; className?: string }>> = {
  kyc_kyb: ShieldCheck, screening: ScrollText, email: Mail,
  tokenization: Coins, onramp: ArrowDownUp, notifications: Bell,
  payments: CreditCard,
};

const DOT: Record<HealthItem["health"], string> = {
  ok:       "bg-success",
  degraded: "bg-warning",
  missing:  "bg-danger/70",
};

const PILL_TONE: Record<HealthItem["health"], string> = {
  ok:       "border-success/30 hover:bg-success/10",
  degraded: "border-warning/40 hover:bg-warning/10",
  missing:  "border-danger/30  hover:bg-danger/10",
};

function timeAgo(iso?: string) {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  const s = Math.floor((Date.now() - t) / 1000);
  if (s < 60)        return `${s}s`;
  if (s < 3600)      return `${Math.floor(s/60)}m`;
  if (s < 24*3600)   return `${Math.floor(s/3600)}h`;
  return `${Math.floor(s / (24*3600))}d`;
}

export default function IntegrationsHealthStrip() {
  const swr = useSWR<HealthResponse>(
    "/v1/admin/settings/integrations/health",
    (p: string) => api(p),
    { refreshInterval: 60_000, revalidateOnFocus: false },
  );
  const items   = swr.data?.items ?? [];
  const counts  = swr.data?.counts;
  const stale   = swr.data?.stale_after_minutes ?? 5;
  const hide403 = swr.error?.status === 403;

  // The endpoint is gated to super_admin + admin. If user is not authorized,
  // hide the strip silently rather than show an error.
  if (hide403) return null;

  return (
    <section
      data-testid="integrations-health-strip"
      className="mb-6 prosper-card p-3">
      <header className="flex items-center justify-between mb-2.5 px-1">
        <div className="flex items-center gap-2">
          <Activity size={12} className="text-fg-subtle"/>
          <h3 className="text-[10px] font-mono uppercase tracking-[0.2em] text-fg-subtle">
            Connection health
          </h3>
          {counts && (
            <span className="text-[10px] font-mono text-fg-subtle">
              · <span className="text-success">{counts.ok}</span> ok
              · <span className="text-warning">{counts.degraded}</span> degraded
              · <span className="text-danger">{counts.missing}</span> missing
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-mono text-fg-subtle">
            re-test cada {stale} min · poll 60s
          </span>
          <button onClick={() => swr.mutate()}
            data-testid="health-refresh"
            disabled={swr.isLoading}
            className="prosper-btn-ghost h-6 px-1.5 text-[10px] gap-1 disabled:opacity-50">
            <RefreshCw size={10} className={swr.isLoading ? "animate-spin" : undefined} />
          </button>
        </div>
      </header>

      <div className="flex flex-wrap gap-1.5">
        {swr.isLoading && items.length === 0 &&
          Array.from({ length: 7 }).map((_, i) => (
            <div key={i} className="h-9 w-32 rounded-full bg-surface-hover/50 animate-pulse" />
          ))}
        {items.map((it) => {
          const Icon = ICON[it.category] || Plug;
          const failingMsg = it.last_test && !it.last_test.ok ? it.last_test.message : null;
          const title = failingMsg
            ? `${it.name} · ${failingMsg}`
            : `${it.name} · ${it.health}${it.last_test?.tested_at
                  ? ` · tested ${timeAgo(it.last_test.tested_at)} ago` : ""}`;
          return (
            <Link key={it.provider}
              href="/admin/settings/integrations"
              title={title}
              data-testid={`health-pill-${it.provider}`}
              className={cn(
                "inline-flex items-center gap-1.5 h-9 px-3 rounded-full",
                "border bg-surface transition-colors text-xs",
                PILL_TONE[it.health],
              )}>
              <Icon size={12} className="text-fg-muted shrink-0" />
              <span className="font-medium text-fg max-w-[120px] truncate">{it.name}</span>
              <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", DOT[it.health])}
                    data-testid={`health-dot-${it.provider}`}/>
              {it.required_total > 0 && (
                <span className="text-[10px] font-mono text-fg-subtle tabular">
                  {it.required_filled}/{it.required_total}
                </span>
              )}
              {it.ran_now && (
                <span className="text-[9px] font-mono uppercase tracking-wider text-primary"
                      title="Re-tested on this request">live</span>
              )}
            </Link>
          );
        })}
      </div>
    </section>
  );
}
