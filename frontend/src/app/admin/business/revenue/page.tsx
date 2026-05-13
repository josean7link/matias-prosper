"use client";
import { PageHeader, DataTable, type Column } from "@prosper/ui";
import {
  ResponsiveContainer, PieChart, Pie, Cell, Tooltip,
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Legend,
} from "recharts";
import { ArrowUp, ArrowDown } from "lucide-react";
import {
  useRevenueSummary, useRevenueBreakdown, useRevenueByMonth, useRevenueByClient,
  CONCEPT_COLOR, CONCEPT_LABEL,
  type RevenueBreakdownItem, type RevenueMonth,
} from "@/lib/business";
import { fmtMoney, cn } from "@/lib/utils";

export default function RevenuePage() {
  const summary = useRevenueSummary();
  const breakdown = useRevenueBreakdown("all");
  const byMonth = useRevenueByMonth(12);
  const byClient = useRevenueByClient(10);

  return (
    <div data-testid="biz-revenue-page" className="space-y-6">
      <PageHeader
        breadcrumbs={[{ label: "Admin", href: "/admin" },
                      { label: "Business", href: "/admin/business" },
                      { label: "Revenue" }]}
        kicker="Phase 4 · Business"
        title="Revenue para Prosper"
        subtitle="Management fees, performance fees, spreads onramp/offramp y comparativas MoM/YoY."
      />

      {/* Stat cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4" data-testid="biz-revenue-summary">
        <StatCard label="Revenue total acumulado"
                  value={fmtMoney(summary.data?.revenue_total)}
                  hint="Desde inicio plataforma" testid="rev-stat-total" />
        <StatCard label="Revenue MTD"
                  value={fmtMoney(summary.data?.revenue_mtd)}
                  delta={summary.data?.mom_delta_pct ?? undefined}
                  hint="vs mes anterior" testid="rev-stat-mtd" />
        <StatCard label="Revenue YTD"
                  value={fmtMoney(summary.data?.revenue_ytd)}
                  delta={summary.data?.yoy_delta_pct ?? undefined}
                  hint="vs año anterior" testid="rev-stat-ytd" />
      </div>

      {/* Breakdown donut + table */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        <div className="prosper-card p-5 lg:col-span-2" data-testid="rev-breakdown-donut">
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
            Breakdown by concept
          </div>
          <h3 className="font-display font-bold text-sm text-fg mt-0.5">Composición · total</h3>
          <div className="mt-3" style={{ height: 220 }}>
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={breakdown.data?.items ?? []} dataKey="amount" nameKey="concept"
                  cx="50%" cy="50%" innerRadius={48} outerRadius={80} paddingAngle={2}>
                  {(breakdown.data?.items ?? []).map((it) => (
                    <Cell key={it.concept} fill={CONCEPT_COLOR[it.concept] || "#6B7280"} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ background: "rgb(var(--surface))",
                    border: "1px solid rgb(var(--border))", borderRadius: 8,
                    fontSize: 12, fontFamily: "var(--font-plex-mono)" }}
                  formatter={(v: number, name: string) =>
                    [fmtMoney(v), CONCEPT_LABEL[name] || name]} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="prosper-card p-5 lg:col-span-3" data-testid="rev-breakdown-table">
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
            Detalle numérico
          </div>
          <h3 className="font-display font-bold text-sm text-fg mt-0.5">Conceptos</h3>
          <table className="mt-3 w-full text-xs">
            <thead>
              <tr className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle border-b border-border">
                <th className="text-left py-2">Concept</th>
                <th className="text-right py-2">Amount</th>
                <th className="text-right py-2 w-32">% Share</th>
              </tr>
            </thead>
            <tbody>
              {(breakdown.data?.items ?? []).map((it: RevenueBreakdownItem) => (
                <tr key={it.concept} className="border-b border-border last:border-0">
                  <td className="py-2.5 flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full"
                          style={{ background: CONCEPT_COLOR[it.concept] }} />
                    {CONCEPT_LABEL[it.concept]}
                  </td>
                  <td className="py-2.5 text-right font-mono tabular">{fmtMoney(it.amount)}</td>
                  <td className="py-2.5 text-right">
                    <div className="inline-flex items-center gap-1 justify-end">
                      <div className="w-16 h-1 rounded bg-surface-hover overflow-hidden">
                        <div className="h-full" style={{
                          width: `${Math.min(100, it.share_pct)}%`,
                          background: CONCEPT_COLOR[it.concept] }} />
                      </div>
                      <span className="font-mono text-[10px] text-fg-subtle w-9 text-right">
                        {it.share_pct.toFixed(1)}%
                      </span>
                    </div>
                  </td>
                </tr>
              ))}
              <tr className="font-bold text-fg border-t border-border">
                <td className="py-2.5">Total</td>
                <td className="py-2.5 text-right font-mono tabular">
                  {fmtMoney(breakdown.data?.total)}
                </td>
                <td />
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* Stacked monthly chart + top clients */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="prosper-card p-5" data-testid="rev-by-month">
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
            Revenue · last 12 months
          </div>
          <h3 className="font-display font-bold text-sm text-fg mt-0.5">Stacked by concept</h3>
          <div className="mt-3" style={{ height: 260 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={byMonth.data?.items ?? []}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--border))" vertical={false}/>
                <XAxis dataKey="month" tick={{ fontSize: 10, fontFamily: "var(--font-plex-mono)",
                  fill: "rgb(var(--fg-subtle))" }} tickLine={false} axisLine={false}
                  tickFormatter={(v: string) => v.slice(2)} />
                <YAxis tickFormatter={(v: number) =>
                  v >= 1000 ? `$${(v/1000).toFixed(0)}K` : `$${v}`}
                  tick={{ fontSize: 10, fontFamily: "var(--font-plex-mono)",
                    fill: "rgb(var(--fg-subtle))" }} tickLine={false} axisLine={false} width={54}/>
                <Tooltip contentStyle={{ background: "rgb(var(--surface))",
                  border: "1px solid rgb(var(--border))", borderRadius: 8,
                  fontSize: 12, fontFamily: "var(--font-plex-mono)" }}
                  formatter={(v: number, name: string) => [fmtMoney(v), CONCEPT_LABEL[name] || name]} />
                <Legend wrapperStyle={{ fontSize: 10, fontFamily: "var(--font-plex-mono)" }} iconType="square" iconSize={8} />
                <Bar dataKey="management"     stackId="r" fill={CONCEPT_COLOR.management} />
                <Bar dataKey="performance"    stackId="r" fill={CONCEPT_COLOR.performance} />
                <Bar dataKey="onramp_spread"  stackId="r" fill={CONCEPT_COLOR.onramp_spread} />
                <Bar dataKey="offramp_spread" stackId="r" fill={CONCEPT_COLOR.offramp_spread} />
                <Bar dataKey="other"          stackId="r" fill={CONCEPT_COLOR.other} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="prosper-card p-5" data-testid="rev-top-clients">
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
            Top 10 clients · revenue
          </div>
          <h3 className="font-display font-bold text-sm text-fg mt-0.5">Concentración</h3>
          <div className="mt-3" style={{ height: 260 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={byClient.data?.items ?? []} layout="vertical" margin={{ left: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--border))" horizontal={false}/>
                <XAxis type="number" tickFormatter={(v: number) =>
                  v >= 1000 ? `$${(v/1000).toFixed(0)}K` : `$${v}`}
                  tick={{ fontSize: 10, fontFamily: "var(--font-plex-mono)",
                    fill: "rgb(var(--fg-subtle))" }} tickLine={false} axisLine={false} />
                <YAxis type="category" dataKey="name" width={120}
                  tick={{ fontSize: 10, fill: "rgb(var(--fg))" }}
                  tickLine={false} axisLine={false}
                  tickFormatter={(v: string) => v.length > 16 ? v.slice(0,15) + "…" : v} />
                <Tooltip contentStyle={{ background: "rgb(var(--surface))",
                  border: "1px solid rgb(var(--border))", borderRadius: 8,
                  fontSize: 12, fontFamily: "var(--font-plex-mono)" }}
                  formatter={(v: number) => [fmtMoney(v), "Revenue"]} />
                <Bar dataKey="revenue" fill="#2563FF" radius={[0, 3, 3, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* MoM comparison */}
      <div className="prosper-card p-5" data-testid="rev-comparison">
        <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
          Comparativas
        </div>
        <h3 className="font-display font-bold text-sm text-fg mt-0.5">Mes actual vs mes anterior</h3>
        <Comparison rows={breakdown.data?.items ?? []} byMonth={byMonth.data?.items ?? []} />
      </div>
    </div>
  );
}

function Comparison({ rows, byMonth }: { rows: RevenueBreakdownItem[]; byMonth: RevenueMonth[] }) {
  // current and prev months from byMonth
  const cur  = byMonth[byMonth.length - 1];
  const prev = byMonth[byMonth.length - 2];
  if (!cur || !prev) {
    return <p className="text-xs text-fg-subtle mt-3">Not enough monthly data.</p>;
  }
  const concepts: (keyof RevenueMonth)[] = ["management", "performance",
    "onramp_spread", "offramp_spread", "other", "total"];
  return (
    <table className="mt-3 w-full text-xs">
      <thead>
        <tr className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle border-b border-border">
          <th className="text-left py-2">Concept</th>
          <th className="text-right py-2">{cur.month}</th>
          <th className="text-right py-2">{prev.month}</th>
          <th className="text-right py-2 w-24">Δ</th>
        </tr>
      </thead>
      <tbody>
        {concepts.map((c) => {
          const curV = cur[c] as number;
          const prevV = prev[c] as number;
          const pct = prevV ? ((curV - prevV) / prevV) * 100 : null;
          const up = (pct ?? 0) >= 0;
          return (
            <tr key={c} className={cn("border-b border-border last:border-0",
                                       c === "total" && "font-bold")}>
              <td className="py-2.5">
                {CONCEPT_LABEL[c as string] || c}
              </td>
              <td className="py-2.5 text-right font-mono tabular">{fmtMoney(curV)}</td>
              <td className="py-2.5 text-right font-mono tabular text-fg-subtle">{fmtMoney(prevV)}</td>
              <td className={cn("py-2.5 text-right font-mono",
                                 pct == null ? "text-fg-subtle"
                                 : up ? "text-success" : "text-danger")}>
                {pct == null ? "—" :
                  <span className="inline-flex items-center gap-0.5">
                    {up ? <ArrowUp size={10} /> : <ArrowDown size={10} />}
                    {pct.toFixed(1)}%
                  </span>}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function StatCard({ label, value, hint, delta, testid }:
  { label: string; value: string; hint?: string; delta?: number; testid: string }) {
  const up = (delta ?? 0) >= 0;
  return (
    <div className="prosper-card p-4" data-testid={testid}>
      <div className="text-[10px] uppercase tracking-[0.15em] font-mono text-fg-subtle">{label}</div>
      <div className="font-display font-extrabold text-2xl text-fg tabular mt-1 leading-tight font-mono">
        {value}
      </div>
      <div className="mt-1.5 flex items-center gap-2 min-h-[16px]">
        {delta != null && (
          <span className={cn("inline-flex items-center gap-0.5 text-[11px] font-mono",
                              up ? "text-success" : "text-danger")}>
            {up ? <ArrowUp size={11} /> : <ArrowDown size={11} />}{delta.toFixed(2)}%
          </span>
        )}
        {hint && <span className="text-[10px] text-fg-subtle font-mono">{hint}</span>}
      </div>
    </div>
  );
}
