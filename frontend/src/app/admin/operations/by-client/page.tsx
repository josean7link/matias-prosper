"use client";
import Link from "next/link";
import { PageHeader, DataTable, type Column } from "@prosper/ui";
import { useByClientStats, type ByClientRow } from "@/lib/operations";
import { fmtNum } from "@/lib/utils";

function Sparkline({ data, color = "#2563FF" }: { data: number[]; color?: string }) {
  if (!data || data.length < 2) {
    return <span className="text-[10px] text-fg-subtle font-mono">—</span>;
  }
  const max = Math.max(...data, 1);
  const w = 64, h = 18;
  const points = data.map((v, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - (v / max) * h;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return (
    <svg width={w} height={h} className="overflow-visible">
      <polyline fill="none" stroke={color} strokeWidth={1.4} points={points}
                strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function ByClientPage() {
  const swr = useByClientStats();
  const cols: Column<ByClientRow>[] = [
    {
      key: "org_name", header: "Client", sortable: true,
      render: (r) => (
        <Link href={`/admin/operations/by-client/${r.org_id}`}
              className="text-fg hover:text-primary">
          {r.org_name}
        </Link>
      ),
    },
    { key: "total",       header: "Total ops",     numeric: true, sortable: true,
      width: "100px",
      render: (r) => <span className="font-mono tabular">{fmtNum(r.total)}</span> },
    { key: "ok",          header: "Successful",    numeric: true, sortable: true,
      width: "110px",
      render: (r) => <span className="font-mono tabular text-success">
        {fmtNum(r.ok)}<span className="text-fg-subtle ml-1">({r.success_pct}%)</span>
      </span> },
    { key: "failed",      header: "Failed",        numeric: true, sortable: true,
      width: "110px",
      render: (r) => <span className="font-mono tabular text-danger">
        {fmtNum(r.failed)}<span className="text-fg-subtle ml-1">({r.failed_pct}%)</span>
      </span> },
    { key: "last_at",     header: "Last op",       width: "150px",
      render: (r) => <span className="font-mono text-[11px]">
        {r.last_at ? new Date(r.last_at).toLocaleString("en-US",
          { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—"}
      </span> },
    { key: "sparkline",   header: "30d activity",  width: "90px",
      render: (r) => <Sparkline data={r.sparkline} /> },
  ];
  return (
    <div data-testid="by-client-page">
      <PageHeader
        breadcrumbs={[{ label: "Admin", href: "/admin" },
                      { label: "Operations", href: "/admin/operations" },
                      { label: "By client" }]}
        kicker="Phase 3 · Operations"
        title="Operaciones por cliente"
        subtitle="Total operaciones, tasa de éxito y actividad reciente por organización."
      />
      <DataTable<ByClientRow>
        data={swr.data?.items ?? []} columns={cols}
        rowKey={(r) => r.org_id}
        empty={swr.isLoading ? "Loading…" : "No clients yet"} />
    </div>
  );
}
