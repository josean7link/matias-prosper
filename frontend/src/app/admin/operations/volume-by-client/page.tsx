"use client";
import Link from "next/link";
import { PageHeader, DataTable, type Column } from "@prosper/ui";
import { ArrowUp, ArrowDown, Minus } from "lucide-react";
import { useVolumeByClient, type VolByClientRow } from "@/lib/operations";
import { fmtMoney, cn } from "@/lib/utils";
import {
  ResponsiveContainer, Treemap, Tooltip,
} from "recharts";

function Delta({ pct }: { pct: number }) {
  if (Math.abs(pct) < 0.01) return (
    <span className="font-mono text-[10px] text-fg-subtle inline-flex items-center gap-0.5">
      <Minus size={10} /> 0%
    </span>);
  const up = pct > 0;
  return (
    <span className={cn(
      "font-mono text-[10px] inline-flex items-center gap-0.5",
      up ? "text-success" : "text-danger",
    )}>
      {up ? <ArrowUp size={10} /> : <ArrowDown size={10} />}
      {pct.toFixed(1)}%
    </span>
  );
}

function ShareBar({ pct }: { pct: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded bg-surface-hover overflow-hidden min-w-[60px]">
        <div className="h-full bg-primary" style={{ width: `${Math.min(100, pct)}%` }} />
      </div>
      <span className="font-mono text-[10px] text-fg-subtle tabular w-10 text-right">
        {pct.toFixed(1)}%
      </span>
    </div>
  );
}

export default function VolumeByClientPage() {
  const swr = useVolumeByClient();

  const cols: Column<VolByClientRow>[] = [
    {
      key: "org_name", header: "Client", sortable: true,
      render: (r) => (
        <Link href={`/admin/operations/by-client/${r.org_id}`}
              className="text-fg hover:text-primary">
          {r.org_name}
        </Link>
      ),
    },
    { key: "vol_24h", header: "24h", numeric: true, sortable: true, width: "110px", align: "right",
      render: (r) => <span className="font-mono tabular">{fmtMoney(r.vol_24h)}</span> },
    { key: "vol_7d",  header: "7d",  numeric: true, sortable: true, width: "120px", align: "right",
      render: (r) => <span className="font-mono tabular">{fmtMoney(r.vol_7d)}</span> },
    { key: "vol_30d", header: "30d  · vs prev", numeric: true, sortable: true, width: "180px", align: "right",
      render: (r) => (
        <div className="text-right">
          <div className="font-mono tabular">{fmtMoney(r.vol_30d)}</div>
          <Delta pct={r.delta_pct_30d} />
        </div>) },
    { key: "vol_total", header: "Acumulado", numeric: true, sortable: true, width: "130px", align: "right",
      render: (r) => <span className="font-mono tabular">{fmtMoney(r.vol_total)}</span> },
    { key: "share_pct_30d", header: "% Share (30d)", width: "180px",
      render: (r) => <ShareBar pct={r.share_pct_30d} /> },
  ];

  const treemapData = (swr.data?.items ?? [])
    .filter((r) => r.vol_30d > 0)
    .slice(0, 20)
    .map((r) => ({ name: r.org_name, size: r.vol_30d }));

  return (
    <div data-testid="volume-by-client-page" className="space-y-6">
      <PageHeader
        breadcrumbs={[{ label: "Admin", href: "/admin" },
                      { label: "Operations", href: "/admin/operations" },
                      { label: "Volume" }]}
        kicker="Phase 3 · Operations"
        title="Volumen por cliente"
        subtitle={`Total 30d · ${fmtMoney(swr.data?.total_volume_30d)} USDC`}
      />

      <div className="prosper-card p-5" data-testid="volume-treemap">
        <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
          Top contribuidores · 30d (treemap)
        </div>
        <div style={{ height: 220 }} className="mt-3">
          <ResponsiveContainer width="100%" height="100%">
            <Treemap data={treemapData} dataKey="size"
                     stroke="rgb(var(--bg))" fill="#2563FF"
                     content={<TreemapCell />}>
              <Tooltip contentStyle={{ background: "rgb(var(--surface))",
                border: "1px solid rgb(var(--border))", borderRadius: 8,
                fontSize: 12, fontFamily: "var(--font-plex-mono)" }}
                formatter={(v: number) => [fmtMoney(v), "Volume"]} />
            </Treemap>
          </ResponsiveContainer>
        </div>
      </div>

      <DataTable<VolByClientRow>
        data={swr.data?.items ?? []} columns={cols}
        rowKey={(r) => r.org_id}
        empty={swr.isLoading ? "Loading…" : "No volume yet"} />
    </div>
  );
}

function TreemapCell(props: any) {
  const { depth, x, y, width, height, name, size } = props;
  if (depth !== 1 || width < 30 || height < 24) return null;
  // gradient by size
  const intensity = Math.min(0.85, 0.25 + (size || 0) / 5_000_000);
  return (
    <g>
      <rect x={x} y={y} width={width} height={height}
            fill="#2563FF" fillOpacity={intensity}
            stroke="rgb(var(--bg))" strokeWidth={2} />
      {width > 60 && height > 32 && (
        <text x={x + 6} y={y + 16} fill="white" fontSize={11}
              fontFamily="var(--font-plex-sans)" fontWeight="600">
          {name.length > 18 ? name.slice(0, 17) + "…" : name}
        </text>
      )}
    </g>
  );
}
