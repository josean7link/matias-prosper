"use client";
import Link from "next/link";
import { useState } from "react";
import { PageHeader, DataTable, type Column } from "@prosper/ui";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
} from "recharts";
import { Eye, EyeOff, Info } from "lucide-react";
import { useYieldByClient, type YieldRow } from "@/lib/business";
import { fmtMoney, cn } from "@/lib/utils";

export default function YieldPage() {
  const [showImplicit, setShowImplicit] = useState(false);
  const swr = useYieldByClient();
  const platformBps = swr.data?.platform_apr_bps ?? 0;

  const baseCols: Column<YieldRow>[] = [
    { key: "name", header: "Client", sortable: true,
      render: (r) => (
        <Link href={`/admin/operations/by-client/${r.org_id}`}
              className="text-fg hover:text-primary">{r.name}</Link>) },
    { key: "principal_usd", header: "Principal", numeric: true, sortable: true,
      width: "130px", align: "right",
      render: (r) => <span className="font-mono tabular">{fmtMoney(r.principal_usd)}</span> },
    { key: "apr_pct", header: showImplicit ? "Net APR" : "APR",
      numeric: true, sortable: true, width: "80px", align: "right",
      render: (r) => <span className="font-mono tabular">{r.apr_pct}%</span> },
  ];

  const implicitCols: Column<YieldRow>[] = [
    { key: "gross_apr_pct", header: "Gross APR", numeric: true, sortable: true,
      width: "90px", align: "right",
      render: (r) => (
        <span className="font-mono tabular text-fg-subtle">{r.gross_apr_pct}%</span>
      ) },
    { key: "implicit_total_pct", header: "Fee drag", numeric: true, sortable: true,
      width: "90px", align: "right",
      render: (r) => (
        <span className="font-mono tabular text-warning">-{r.implicit_total_pct}%</span>
      ) },
    { key: "implicit_mgmt_30d_usd", header: "Mgmt 30d", numeric: true, sortable: true,
      width: "100px", align: "right",
      render: (r) => <span className="font-mono tabular">
        {fmtMoney(r.implicit_mgmt_30d_usd)}</span> },
    { key: "implicit_perf_30d_usd", header: "Perf 30d", numeric: true, sortable: true,
      width: "100px", align: "right",
      render: (r) => <span className="font-mono tabular">
        {fmtMoney(r.implicit_perf_30d_usd)}</span> },
    { key: "implicit_total_30d_usd", header: "Prosper rev 30d", numeric: true, sortable: true,
      width: "130px", align: "right",
      render: (r) => <span className="font-mono tabular text-success">
        {fmtMoney(r.implicit_total_30d_usd)}</span> },
  ];

  const tailCols: Column<YieldRow>[] = [
    { key: "accrued_30d", header: "Accrued 30d", numeric: true, sortable: true,
      width: "120px", align: "right",
      render: (r) => <span className="font-mono tabular text-success">{fmtMoney(r.accrued_30d)}</span> },
    { key: "accrued_total", header: "Accrued total", numeric: true, sortable: true,
      width: "130px", align: "right",
      render: (r) => <span className="font-mono tabular">{fmtMoney(r.accrued_total)}</span> },
    { key: "next_payout_at", header: "Next payout", width: "180px",
      render: (r) => r.next_payout_at ? (
        <div>
          <div className="font-mono text-[11px]">{r.next_payout_at.slice(0,10)}</div>
          <div className="text-[10px] text-fg-subtle font-mono">~{fmtMoney(r.next_payout_usd)}</div>
        </div>
      ) : <span className="text-fg-subtle">—</span> },
    { key: "benchmark_delta_bps", header: "vs platform", numeric: true,
      width: "110px", align: "right",
      render: (r) => {
        const up = r.benchmark_delta_bps >= 0;
        return (
          <span className={cn("font-mono tabular text-[11px]",
                               up ? "text-success" : "text-danger")}>
            {up ? "+" : ""}{(r.benchmark_delta_bps / 100).toFixed(2)}%
          </span>
        );
      },
    },
  ];

  const cols: Column<YieldRow>[] = showImplicit
    ? [...baseCols, ...implicitCols, ...tailCols]
    : [...baseCols, ...tailCols];

  const chartData = (swr.data?.items ?? []).slice(0, 20)
    .map((r) => ({ name: r.name, accrued: r.accrued_30d }));

  return (
    <div data-testid="biz-yield-page" className="space-y-6">
      <PageHeader
        breadcrumbs={[{ label: "Admin", href: "/admin" },
                      { label: "Business", href: "/admin/business" },
                      { label: "Rendimientos" }]}
        kicker="Phase 4 · Business"
        title="Rendimientos por cliente"
        subtitle={`Platform-wide APR · ${swr.data?.platform_apr_pct ?? "—"}% · ${platformBps} bps`}
        actions={
          <button
            onClick={() => setShowImplicit((v) => !v)}
            data-testid="biz-yield-toggle-implicit"
            aria-pressed={showImplicit}
            className={cn(
              "h-9 px-3 rounded-md text-xs gap-1.5 inline-flex items-center transition-colors",
              showImplicit
                ? "bg-fg text-bg hover:bg-fg/90"
                : "border border-border text-fg hover:bg-surface-hover",
            )}>
            {showImplicit ? <EyeOff size={13}/> : <Eye size={13}/>}
            {showImplicit ? "Ocultar fees implícitos" : "Mostrar fees implícitos"}
          </button>
        }
      />

      {showImplicit && (
        <div className="prosper-card p-4 bg-surface-hover border-border"
             data-testid="biz-yield-implicit-banner">
          <div className="flex items-start gap-2.5">
            <Info size={14} className="text-warning mt-0.5 shrink-0" />
            <div className="text-[11px] font-mono text-fg-muted leading-relaxed">
              <span className="text-fg font-semibold">Modelo de fees implícitos · Prosper.</span>{" "}
              Management <span className="text-fg">1% anual</span> sobre principal +
              performance <span className="text-fg">10%</span> del rendimiento bruto.
              <span className="block mt-1">
                <span className="text-fg">Gross APR</span> = rendimiento bruto del fondo ·
                <span className="text-fg ml-1">Net APR</span> = entregado al cliente ·
                <span className="text-fg ml-1">Fee drag</span> = diferencia.
                Importes 30d obtenidos del <span className="text-fg">fee_breakdown</span> real
                de las transacciones.
              </span>
            </div>
          </div>
        </div>
      )}

      <div className="prosper-card p-5" data-testid="yield-top-chart">
        <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
          Top 20 · accrued 30d
        </div>
        <div className="mt-3" style={{ height: 260 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--border))" vertical={false} />
              <XAxis dataKey="name" hide tickLine={false} axisLine={false} />
              <YAxis tickFormatter={(v: number) =>
                v >= 1000 ? `$${(v/1000).toFixed(0)}K` : `$${v}`}
                tick={{ fontSize: 10, fontFamily: "var(--font-plex-mono)",
                  fill: "rgb(var(--fg-subtle))" }}
                tickLine={false} axisLine={false} width={54}/>
              <Tooltip contentStyle={{ background: "rgb(var(--surface))",
                border: "1px solid rgb(var(--border))", borderRadius: 8,
                fontSize: 12, fontFamily: "var(--font-plex-mono)" }}
                formatter={(v: number) => [fmtMoney(v), "Accrued 30d"]} />
              <Bar dataKey="accrued" fill="#22C55E" radius={[3,3,0,0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <DataTable<YieldRow>
        data={swr.data?.items ?? []} columns={cols}
        rowKey={(r) => r.org_id}
        empty={swr.isLoading ? "Loading…" : "No yield data"} />
    </div>
  );
}
