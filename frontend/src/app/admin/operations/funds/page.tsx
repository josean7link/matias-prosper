"use client";
import { PageHeader, Badge, StatusDot } from "@prosper/ui";
import { useTranslations } from "next-intl";
import { Copy, ExternalLink, Wifi, ShieldCheck, Power } from "lucide-react";
import { toast } from "sonner";
import useSWR from "swr";
import { useFundsState, useUpstreamStatus } from "@/lib/operations";
import { api } from "@/lib/api";
import { fmtMoney, cn } from "@/lib/utils";
import {
  ResponsiveContainer, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
} from "recharts";

export default function FundsPage() {
  const tH = useTranslations("admin.headers");
  const tA = useTranslations("admin");
  const funds  = useFundsState();
  const status = useUpstreamStatus();
  const nav    = useSWR<{ items: { date: string; nav: number }[] }>(
    "/v1/admin/dashboard/nav-history?days=90", (p: string) => api(p));

  const f = funds.data?.fund;

  const navDelta = f?.nav_delta_24h;
  const navUp    = (navDelta ?? 0) >= 0;

  return (
    <div data-testid="funds-page" className="space-y-6">
      <PageHeader
        breadcrumbs={[{ label: tA("breadcrumb_admin"), href: "/admin" },
                      { label: tH("ops_label"), href: "/admin/operations" },
                      { label: tH("ops_funds_bc") }]}
        kicker={tH("ops_funds_kicker")}
        title={tH("ops_funds_title")}
        subtitle={tH("ops_funds_subtitle")}
      />

      {/* Fund header card */}
      <div className="prosper-card p-6" data-testid="fund-header">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
              Fund · {f?.fund_id || "loading"}
            </div>
            <h2 className="font-display font-extrabold text-2xl text-fg mt-0.5">
              {f?.name || "—"}
            </h2>
            <div className="mt-1 text-xs text-fg-muted">
              Asset code · <span className="font-mono">{f?.asset_code || "PROS"}</span>
              <span className="mx-2">·</span>
              {f?.positions ?? 0} positions
            </div>
          </div>
        </div>
        <div className="mt-5 grid grid-cols-2 md:grid-cols-4 gap-4">
          <Stat label="NAV"
                value={f ? f.nav.toFixed(6) : "—"}
                delta={navDelta ?? undefined}
                tone={navUp ? "success" : "danger"}
                testid="fund-stat-nav" />
          <Stat label="Supply circulating"
                value={f ? fmtMoney(f.supply_circulating) : "—"}
                hint={`${f?.asset_code || ""} tokens`}
                testid="fund-stat-supply" />
          <Stat label="Total invested"
                value={f ? fmtMoney(f.invested_usd) : "—"}
                hint="principal + accrued"
                testid="fund-stat-invested" />
          <Stat label="Treasury balance"
                value={f ? fmtMoney(f.treasury_usd) : "—"}
                hint="available for redeem"
                testid="fund-stat-treasury" />
        </div>
      </div>

      {/* NAV chart 90d */}
      <div className="prosper-card p-5" data-testid="fund-nav-chart">
        <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">NAV</div>
        <div className="text-[11px] text-fg-subtle font-mono">Daily net asset value · 90 days</div>
        <div className="mt-3" style={{ height: 260 }}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={nav.data?.items ?? []}>
              <defs>
                <linearGradient id="navg" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%"  stopColor="#2563FF" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="#2563FF" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--border))" vertical={false}/>
              <XAxis dataKey="date" tickFormatter={(v: string) => v.slice(5)}
                tick={{ fontSize: 10, fontFamily: "var(--font-plex-mono)",
                        fill: "rgb(var(--fg-subtle))" }}
                tickLine={false} axisLine={false} minTickGap={28} />
              <YAxis domain={[(d: number) => +(d - 0.002).toFixed(4),
                              (d: number) => +(d + 0.002).toFixed(4)]}
                tickFormatter={(v: number) => v.toFixed(4)}
                tick={{ fontSize: 10, fontFamily: "var(--font-plex-mono)",
                        fill: "rgb(var(--fg-subtle))" }}
                tickLine={false} axisLine={false} width={60}/>
              <Tooltip contentStyle={{ background: "rgb(var(--surface))",
                border: "1px solid rgb(var(--border))", borderRadius: 8,
                fontSize: 12, fontFamily: "var(--font-plex-mono)" }}
                formatter={(v: number) => [v.toFixed(6), "NAV"]}/>
              <Area type="monotone" dataKey="nav" stroke="#2563FF"
                    strokeWidth={2} fill="url(#navg)" dot={false}/>
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Stellar accounts */}
        <div className="prosper-card lg:col-span-2 overflow-hidden"
             data-testid="stellar-accounts">
          <div className="px-4 py-3 border-b border-border bg-surface">
            <h3 className="font-display font-bold text-sm text-fg">Stellar accounts</h3>
            <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mt-0.5">
              XLM reserve total · {funds.data?.xlm_reserve_total ?? "—"}
            </div>
          </div>
          <ul>
            {funds.data?.stellar_accounts.map((a) => (
              <li key={a.label} data-testid={`stellar-${a.label.toLowerCase().replace(/\W+/g,'-')}`}
                  className="px-4 py-3 border-b border-border last:border-0
                             flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-xs text-fg font-medium">{a.label}</div>
                  <div className="flex items-center gap-1 mt-0.5">
                    <span className="font-mono text-[10.5px] text-fg-subtle"
                          title={a.address}>
                      {a.address.slice(0, 8)}…{a.address.slice(-6)}
                    </span>
                    <button onClick={() => {
                      navigator.clipboard.writeText(a.address);
                      toast.success("Address copied");
                    }} className="text-fg-subtle hover:text-primary"
                       data-testid={`copy-addr-${a.label.toLowerCase().replace(/\W+/g,'-')}`}>
                      <Copy size={11} />
                    </button>
                    <a href={`https://stellar.expert/explorer/public/account/${a.address}`}
                       target="_blank" rel="noreferrer"
                       className="text-fg-subtle hover:text-primary">
                      <ExternalLink size={11} />
                    </a>
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="font-mono tabular text-sm">{fmtMoney(a.balance_usd)}</div>
                  <div className="font-mono text-[10px] text-fg-subtle">
                    {a.balance_xlm.toFixed(2)} XLM
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>

        {/* Upstream status semaphore */}
        <div className="prosper-card p-5" data-testid="upstream-status">
          <h3 className="font-display font-bold text-sm text-fg">Stellar upstream</h3>
          <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mt-0.5">
            {status.data?.upstream_url || "horizon.stellar.org"}
          </div>
          <div className="mt-4 space-y-2.5">
            <LED label="Enabled"       on={status.data?.enabled ?? false}     icon={<Power size={12} />} testid="led-enabled" />
            <LED label="Reachable"     on={status.data?.reachable ?? false}   icon={<Wifi size={12} />}  testid="led-reachable" />
            <LED label="Authenticated" on={status.data?.authenticated ?? false} icon={<ShieldCheck size={12} />} testid="led-auth" />
          </div>
          {status.data?.note && (
            <p className="mt-4 text-[10px] font-mono text-warning bg-warning/10
                          border border-warning/20 rounded p-2 leading-snug">
              {status.data.note}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, hint, delta, tone, testid }:
  { label: string; value: string; hint?: string;
    delta?: number; tone?: "success" | "danger" | "primary"; testid: string }) {
  return (
    <div className="border border-border rounded p-3" data-testid={testid}>
      <div className="text-[10px] uppercase tracking-[0.15em] font-mono text-fg-subtle">
        {label}
      </div>
      <div className="font-display font-extrabold text-xl text-fg tabular mt-1 leading-tight font-mono">
        {value}
      </div>
      <div className="mt-0.5 min-h-[16px] text-[10px] font-mono">
        {delta != null && (
          <span className={cn(tone === "success" ? "text-success" : "text-danger")}>
            {delta >= 0 ? "▲" : "▼"} {(delta * 100).toFixed(2)}%
          </span>
        )}
        {hint && <span className="text-fg-subtle"> {hint}</span>}
      </div>
    </div>
  );
}

function LED({ label, on, icon, testid }: { label: string; on: boolean; icon: React.ReactNode; testid: string }) {
  return (
    <div className="flex items-center gap-3" data-testid={testid}>
      <StatusDot color={on ? "green" : "red"} pulse={!on} />
      <span className="text-fg-muted">{icon}</span>
      <span className="text-xs flex-1">{label}</span>
      <Badge tone={on ? "success" : "danger"} size="sm">{on ? "ok" : "down"}</Badge>
    </div>
  );
}
