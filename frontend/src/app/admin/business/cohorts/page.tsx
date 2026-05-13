"use client";
import { useState } from "react";
import { PageHeader, DataTable, type Column } from "@prosper/ui";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, LineChart, Line,
} from "recharts";
import { useCohorts, type CohortRow } from "@/lib/business";
import { fmtMoney, cn } from "@/lib/utils";

const RANGES: { value: number; label: string }[] = [
  { value: 6,  label: "6 m" },
  { value: 12, label: "12 m" },
  { value: 24, label: "24 m" },
];

export default function CohortsPage() {
  const [months, setMonths] = useState(12);
  const swr = useCohorts(months);
  const items   = swr.data?.items   ?? [];
  const totals  = swr.data?.totals;

  const cols: Column<CohortRow>[] = [
    { key: "cohort_month", header: "Cohort", sortable: true, width: "110px",
      render: (r) => <span className="font-mono text-xs">{r.cohort_month}</span> },
    { key: "new_clients", header: "New", numeric: true, sortable: true, width: "80px", align: "right",
      render: (r) => <span className="font-mono tabular">{r.new_clients}</span> },
    { key: "active_now", header: "Active now", numeric: true, sortable: true,
      width: "110px", align: "right",
      render: (r) => <span className="font-mono tabular text-success">{r.active_now}</span> },
    { key: "churned", header: "Churned", numeric: true, sortable: true,
      width: "100px", align: "right",
      render: (r) => <span className={cn("font-mono tabular",
        r.churned > 0 ? "text-danger" : "text-fg-subtle")}>{r.churned}</span> },
    { key: "retention_pct", header: "Retention", numeric: true, sortable: true,
      width: "120px", align: "right",
      render: (r) => (
        <div className="inline-flex items-center gap-1.5 justify-end">
          <div className="w-12 h-1 rounded bg-surface-hover overflow-hidden">
            <div className="h-full bg-success"
                 style={{ width: `${Math.min(100, r.retention_pct)}%` }}/>
          </div>
          <span className="font-mono tabular text-[11px] w-12 text-right">{r.retention_pct}%</span>
        </div>
      ) },
    { key: "volume_total", header: "Volume", numeric: true, sortable: true,
      width: "130px", align: "right",
      render: (r) => <span className="font-mono tabular">{fmtMoney(r.volume_total)}</span> },
    { key: "revenue_total", header: "Revenue", numeric: true, sortable: true,
      width: "130px", align: "right",
      render: (r) => <span className="font-mono tabular text-success">
        {fmtMoney(r.revenue_total)}</span> },
    { key: "avg_revenue_per_client", header: "Avg rev/client", numeric: true, sortable: true,
      width: "130px", align: "right",
      render: (r) => <span className="font-mono tabular">
        {fmtMoney(r.avg_revenue_per_client)}</span> },
  ];

  return (
    <div data-testid="biz-cohorts-page" className="space-y-6">
      <PageHeader
        breadcrumbs={[{ label: "Admin", href: "/admin" },
                      { label: "Business", href: "/admin/business" },
                      { label: "Cohortes" }]}
        kicker="Phase 4 · Business"
        title="Análisis de cohortes"
        subtitle="Adquisición, retención y revenue por mes de primera suscripción."
        actions={
          <div className="inline-flex rounded-md border border-border overflow-hidden"
               data-testid="cohorts-range">
            {RANGES.map((r) => (
              <button key={r.value}
                onClick={() => setMonths(r.value)}
                data-testid={`cohorts-range-${r.value}`}
                aria-pressed={months === r.value}
                className={cn(
                  "h-9 px-3 text-xs font-mono uppercase tracking-wider transition-colors",
                  months === r.value
                    ? "bg-fg text-bg"
                    : "bg-surface text-fg-muted hover:text-fg",
                )}>{r.label}</button>
            ))}
          </div>
        }
      />

      {/* Totals strip */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3" data-testid="cohorts-totals">
        <Tile label="New clients"      value={totals?.new_clients ?? "—"} testid="cohorts-tile-new" />
        <Tile label="Active now"       value={totals?.active_now ?? "—"} success
              testid="cohorts-tile-active" />
        <Tile label="Avg retention"
              value={totals ? `${totals.retention_pct}%` : "—"}
              testid="cohorts-tile-retention" />
        <Tile label="Revenue · cohorts"
              value={totals ? fmtMoney(totals.revenue_total) : "—"} mono
              testid="cohorts-tile-revenue" />
      </div>

      {/* Acquisition + retention chart */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="prosper-card p-5" data-testid="cohorts-acq-chart">
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
            Adquisición vs churn
          </div>
          <h3 className="font-display font-bold text-sm text-fg mt-0.5">
            Clientes nuevos por mes (activos vs churned)
          </h3>
          <div className="mt-3" style={{ height: 240 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={items}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--border))" vertical={false}/>
                <XAxis dataKey="cohort_month"
                  tick={{ fontSize: 10, fontFamily: "var(--font-plex-mono)",
                    fill: "rgb(var(--fg-subtle))" }}
                  tickLine={false} axisLine={false}
                  tickFormatter={(v: string) => v.slice(2)} />
                <YAxis allowDecimals={false}
                  tick={{ fontSize: 10, fontFamily: "var(--font-plex-mono)",
                    fill: "rgb(var(--fg-subtle))" }}
                  tickLine={false} axisLine={false} width={36}/>
                <Tooltip contentStyle={{ background: "rgb(var(--surface))",
                  border: "1px solid rgb(var(--border))", borderRadius: 8,
                  fontSize: 12, fontFamily: "var(--font-plex-mono)" }} />
                <Legend wrapperStyle={{ fontSize: 10, fontFamily: "var(--font-plex-mono)" }}
                        iconType="square" iconSize={8}/>
                <Bar dataKey="active_now" name="Active" stackId="c" fill="#22C55E" />
                <Bar dataKey="churned"    name="Churned" stackId="c" fill="#DC2626" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="prosper-card p-5" data-testid="cohorts-ret-chart">
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
            Retención
          </div>
          <h3 className="font-display font-bold text-sm text-fg mt-0.5">
            % de retención por cohorte
          </h3>
          <div className="mt-3" style={{ height: 240 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={items}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--border))" vertical={false}/>
                <XAxis dataKey="cohort_month"
                  tick={{ fontSize: 10, fontFamily: "var(--font-plex-mono)",
                    fill: "rgb(var(--fg-subtle))" }}
                  tickLine={false} axisLine={false}
                  tickFormatter={(v: string) => v.slice(2)} />
                <YAxis domain={[0, 100]} tickFormatter={(v: number) => `${v}%`}
                  tick={{ fontSize: 10, fontFamily: "var(--font-plex-mono)",
                    fill: "rgb(var(--fg-subtle))" }}
                  tickLine={false} axisLine={false} width={40}/>
                <Tooltip contentStyle={{ background: "rgb(var(--surface))",
                  border: "1px solid rgb(var(--border))", borderRadius: 8,
                  fontSize: 12, fontFamily: "var(--font-plex-mono)" }}
                  formatter={(v: number) => [`${v}%`, "Retention"]} />
                <Line type="monotone" dataKey="retention_pct"
                  stroke="#2563FF" strokeWidth={2}
                  dot={{ r: 3, fill: "#2563FF" }}
                  activeDot={{ r: 5 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <DataTable<CohortRow>
        data={items}
        columns={cols}
        rowKey={(r) => r.cohort_month}
        empty={swr.isLoading ? "Loading…" : "No cohort data"} />
    </div>
  );
}

function Tile({ label, value, hint, mono, success, testid }:
  { label: string; value: string | number; hint?: string;
    mono?: boolean; success?: boolean; testid: string }) {
  return (
    <div className="prosper-card p-4" data-testid={testid}>
      <div className="text-[10px] uppercase tracking-[0.15em] font-mono text-fg-subtle">{label}</div>
      <div className={cn("font-display font-extrabold text-xl tabular mt-1 leading-tight",
                          mono && "font-mono",
                          success ? "text-success" : "text-fg")}>
        {value}
      </div>
      {hint && <div className="text-[10px] text-fg-subtle font-mono mt-1">{hint}</div>}
    </div>
  );
}
