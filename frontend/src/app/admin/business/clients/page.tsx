"use client";
import Link from "next/link";
import { useMemo, useState } from "react";
import { PageHeader, Badge, DataTable, type Column } from "@prosper/ui";
import { Download } from "lucide-react";
import { useBizClients, type BizClient } from "@/lib/business";
import { fmtMoney, cn } from "@/lib/utils";
import BusinessExecutivePdfButton from "@/components/business/ExecutivePdfButton";

function Sparkline({ data }: { data: number[] }) {
  if (!data || data.length < 2) {
    return <span className="text-[10px] text-fg-subtle font-mono">—</span>;
  }
  const max = Math.max(...data, 1);
  const w = 72, h = 18;
  const points = data.map((v, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - (v / max) * h;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return (
    <svg width={w} height={h} className="overflow-visible">
      <polyline fill="none" stroke="#2563FF" strokeWidth={1.4} points={points}
                strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function ClientsPage() {
  const [typeFilter, setTypeFilter] = useState<string[]>([]);
  const swr = useBizClients({ type: typeFilter.length ? typeFilter : undefined });

  const TYPES = useMemo(() => {
    const s = new Set<string>();
    swr.data?.items.forEach((i) => i.type && s.add(i.type));
    return Array.from(s);
  }, [swr.data]);

  const cols: Column<BizClient>[] = [
    { key: "name", header: "Client", sortable: true,
      render: (r) => (
        <Link href={`/admin/operations/by-client/${r.org_id}`}
              className="text-fg hover:text-primary">{r.name}</Link>) },
    { key: "type", header: "Type", width: "120px",
      render: (r) => <Badge tone="auto" size="sm">{r.type || "—"}</Badge> },
    { key: "status", header: "Status", width: "100px",
      render: (r) => <Badge tone={r.status === "active" ? "success" : "warning"} size="sm">
        {r.status}</Badge> },
    { key: "tier", header: "Tier", width: "70px",
      render: (r) => <span className="font-mono text-[11px]">{r.tier}</span> },
    { key: "volume_total", header: "Volume total", numeric: true, sortable: true,
      width: "140px", align: "right",
      render: (r) => <span className="font-mono tabular">{fmtMoney(r.volume_total)}</span> },
    { key: "revenue_total", header: "Revenue", numeric: true, sortable: true,
      width: "120px", align: "right",
      render: (r) => <span className="font-mono tabular text-success">{fmtMoney(r.revenue_total)}</span> },
    { key: "apr_effective_pct", header: "APR", numeric: true, width: "70px", align: "right",
      render: (r) => <span className="font-mono tabular">{r.apr_effective_pct}%</span> },
    { key: "yield_30d_pct", header: "Yield 30d", numeric: true, width: "90px", align: "right",
      render: (r) => <span className="font-mono tabular text-success">{r.yield_30d_pct}%</span> },
    { key: "started_at", header: "Started", width: "110px",
      render: (r) => <span className="font-mono text-[10px]">
        {r.started_at ? r.started_at.slice(0, 10) : "—"}</span> },
    { key: "sparkline", header: "30d vol", width: "90px",
      render: (r) => <Sparkline data={r.sparkline} /> },
  ];

  const exportUrl = useMemo(() => {
    const p = new URLSearchParams();
    typeFilter.forEach((t) => p.append("type", t));
    return `/api/v1/admin/business/clients/export.csv?${p.toString()}`;
  }, [typeFilter]);

  return (
    <div data-testid="biz-clients-page">
      <PageHeader
        breadcrumbs={[{ label: "Admin", href: "/admin" },
                      { label: "Business", href: "/admin/business" },
                      { label: "Clientes" }]}
        kicker="Phase 4 · Business"
        title="Listado maestro de clientes"
        subtitle="Volumen, revenue generado para Prosper y rendimiento entregado por organización."
        actions={
          <div className="flex items-center gap-2">
            <a href={exportUrl} target="_blank" rel="noreferrer"
               data-testid="biz-clients-export-csv"
               className="prosper-btn-ghost h-9 text-xs gap-1.5">
              <Download size={13} /> CSV
            </a>
            <BusinessExecutivePdfButton />
          </div>
        }
      />

      {/* Type chips */}
      {TYPES.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 mb-4" data-testid="biz-clients-filters">
          <span className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mr-1">Type</span>
          {TYPES.map((t) => {
            const active = typeFilter.includes(t);
            return (
              <button key={t}
                onClick={() => setTypeFilter((arr) =>
                  arr.includes(t) ? arr.filter((x) => x !== t) : [...arr, t])}
                data-testid={`biz-chip-type-${t}`}
                className={cn(
                  "h-7 px-2.5 rounded-full text-[10px] font-mono uppercase tracking-wider",
                  active
                    ? "bg-fg text-bg"
                    : "bg-surface text-fg-muted hover:text-fg border border-border",
                )}>
                {t}
              </button>
            );
          })}
        </div>
      )}

      <DataTable<BizClient>
        data={swr.data?.items ?? []} columns={cols}
        rowKey={(r) => r.org_id}
        empty={swr.isLoading ? "Loading…" : "No clients"} />
    </div>
  );
}
