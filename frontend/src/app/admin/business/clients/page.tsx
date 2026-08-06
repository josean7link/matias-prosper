"use client";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { PageHeader, Badge, DataTable, type Column } from "@prosper/ui";
import { Download, Columns3, Check } from "lucide-react";
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

// Column metadata — `key` MUST match a BizClient field name. Required columns
// (`name`) can't be toggled off.
type ColKey = "name" | "parent" | "level" | "type" | "status" | "tier"
  | "volume_total" | "revenue_total" | "apr_effective_pct" | "yield_30d_pct"
  | "started_at" | "sparkline";

interface ColMeta { key: ColKey; label: string; required?: boolean; defaultOn: boolean }
const COL_META: ColMeta[] = [
  { key: "name",              label: "Client",     required: true, defaultOn: true  },
  { key: "parent",            label: "Parent",     defaultOn: true  },
  { key: "level",             label: "Nivel",      defaultOn: true  },
  { key: "type",              label: "Type",       defaultOn: true  },
  { key: "status",            label: "Status",     defaultOn: true  },
  { key: "tier",              label: "Tier",       defaultOn: true  },
  { key: "volume_total",      label: "Volume",     defaultOn: true  },
  { key: "revenue_total",     label: "Revenue",    defaultOn: true  },
  { key: "apr_effective_pct", label: "APR",        defaultOn: true  },
  { key: "yield_30d_pct",     label: "Yield 30d",  defaultOn: true  },
  { key: "started_at",        label: "Started",    defaultOn: true  },
  { key: "sparkline",         label: "30d vol",    defaultOn: true  },
];
const STORAGE_KEY = "prosper.biz.clients.cols.v2";

type HierarchyFilter = "all" | "n1" | "n2";

export default function ClientsPage() {
  const [typeFilter, setTypeFilter] = useState<string[]>([]);
  const [hierarchy, setHierarchy] = useState<HierarchyFilter>("all");
  const swr = useBizClients({
    type: typeFilter.length ? typeFilter : undefined,
    parent_org_id: hierarchy === "n1" ? "none" : undefined,
  });

  // Persisted visible-columns set
  const [visible, setVisible] = useState<Set<ColKey>>(() => new Set(
    COL_META.filter((c) => c.defaultOn).map((c) => c.key)));
  // Restore from localStorage after mount (avoid SSR/CSR mismatch)
  const restored = useRef(false);
  useEffect(() => {
    if (restored.current) return;
    restored.current = true;
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const arr = JSON.parse(raw) as ColKey[];
        const next = new Set<ColKey>(arr);
        COL_META.forEach((c) => { if (c.required) next.add(c.key); });
        setVisible(next);
      }
    } catch { /* ignore */ }
  }, []);
  useEffect(() => {
    if (!restored.current) return;
    try {
      window.localStorage.setItem(STORAGE_KEY,
        JSON.stringify(Array.from(visible)));
    } catch { /* ignore */ }
  }, [visible]);

  const TYPES = useMemo(() => {
    const s = new Set<string>();
    swr.data?.items.forEach((i) => i.type && s.add(i.type));
    return Array.from(s);
  }, [swr.data]);

  const allCols: Record<ColKey, Column<BizClient>> = {
    name: { key: "name", header: "Client", sortable: true,
      render: (r) => (
        <Link href={`/admin/operations/by-client/${r.org_id}`}
              className="text-fg hover:text-primary">{r.name}</Link>) },
    parent: { key: "parent", header: "Parent", width: "150px",
      render: (r) => r.parent_org_id ? (
        <Link href={`/admin/operations/by-client/${r.parent_org_id}`}
              className="text-fg-muted hover:text-primary text-xs"
              data-testid={`biz-row-parent-${r.org_id}`}>
          {r.parent_name || r.parent_org_id}
        </Link>
      ) : <span className="text-fg-subtle text-[10px] font-mono">—</span> },
    level: { key: "level", header: "Nivel", width: "70px",
      render: (r) => (
        <Badge tone={r.level === 1 ? "info" : "warning"} size="sm"
                data-testid={`biz-row-level-${r.org_id}`}>
          N{r.level}
        </Badge>) },
    type: { key: "type", header: "Type", width: "120px",
      render: (r) => <Badge tone="auto" size="sm">{r.type || "—"}</Badge> },
    status: { key: "status", header: "Status", width: "100px",
      render: (r) => <Badge tone={r.status === "active" ? "success" : "warning"} size="sm">
        {r.status}</Badge> },
    tier: { key: "tier", header: "Tier", width: "70px",
      render: (r) => <span className="font-mono text-[11px]">{r.tier}</span> },
    volume_total: { key: "volume_total", header: "Volume total", numeric: true, sortable: true,
      width: "140px", align: "right",
      render: (r) => <span className="font-mono tabular">{fmtMoney(r.volume_total)}</span> },
    revenue_total: { key: "revenue_total", header: "Revenue", numeric: true, sortable: true,
      width: "120px", align: "right",
      render: (r) => <span className="font-mono tabular text-success">{fmtMoney(r.revenue_total)}</span> },
    apr_effective_pct: { key: "apr_effective_pct", header: "APR", numeric: true, width: "70px", align: "right",
      render: (r) => <span className="font-mono tabular">{r.apr_effective_pct}%</span> },
    yield_30d_pct: { key: "yield_30d_pct", header: "Yield 30d", numeric: true, width: "90px", align: "right",
      render: (r) => <span className="font-mono tabular text-success">{r.yield_30d_pct}%</span> },
    started_at: { key: "started_at", header: "Started", width: "110px",
      render: (r) => <span className="font-mono text-[10px]">
        {r.started_at ? r.started_at.slice(0, 10) : "—"}</span> },
    sparkline: { key: "sparkline", header: "30d vol", width: "90px",
      render: (r) => <Sparkline data={r.sparkline} /> },
  };
  const cols = COL_META.filter((c) => visible.has(c.key)).map((c) => allCols[c.key]);

  const exportUrl = useMemo(() => {
    const p = new URLSearchParams();
    typeFilter.forEach((t) => p.append("type", t));
    return `/api/v1/admin/business/clients/export.csv?${p.toString()}`;
  }, [typeFilter]);

  const tH = useTranslations("admin.headers");
  const tA = useTranslations("admin");

  return (
    <div data-testid="biz-clients-page">
      <PageHeader
        breadcrumbs={[{ label: tA("breadcrumb_admin"), href: "/admin" },
                      { label: tH("bus_label"), href: "/admin/business" },
                      { label: tH("bus_clients_bc") }]}
        kicker={tH("bus_clients_kicker")}
        title={tH("bus_clients_title")}
        subtitle={tH("bus_clients_subtitle")}
        actions={
          <div className="flex items-center gap-2">
            <ColumnsDropdown visible={visible} setVisible={setVisible} />
            <a href={exportUrl} target="_blank" rel="noreferrer"
               data-testid="biz-clients-export-csv"
               className="prosper-btn-ghost h-9 text-xs gap-1.5">
              <Download size={13} /> CSV
            </a>
            <BusinessExecutivePdfButton />
          </div>
        }
      />

      {/* Hierarchy filter (Phase 23) + Type chips */}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <div className="flex flex-wrap items-center gap-1.5"
             data-testid="biz-clients-hierarchy-filter">
          <span className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mr-1">
            Jerarquía
          </span>
          {(["all", "n1", "n2"] as HierarchyFilter[]).map((h) => {
            const active = hierarchy === h;
            return (
              <button key={h}
                onClick={() => setHierarchy(h)}
                data-testid={`biz-chip-hierarchy-${h}`}
                className={cn(
                  "h-7 px-2.5 rounded-full text-[10px] font-mono uppercase tracking-wider",
                  active
                    ? "bg-fg text-bg"
                    : "bg-surface text-fg-muted hover:text-fg border border-border",
                )}>
                {h === "all" ? "Todos" : h.toUpperCase()}
              </button>
            );
          })}
        </div>

        {TYPES.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5" data-testid="biz-clients-filters">
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
      </div>

      <DataTable<BizClient>
        data={(swr.data?.items ?? []).filter(
          (r) => hierarchy === "n2" ? (r.level || 1) >= 2 : true)} columns={cols}
        rowKey={(r) => r.org_id}
        empty={swr.isLoading ? "Loading…" : "No clients"} />
    </div>
  );
}

function ColumnsDropdown({ visible, setVisible }:
  { visible: Set<ColKey>; setVisible: (v: Set<ColKey>) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);
  const toggle = (k: ColKey) => {
    const meta = COL_META.find((c) => c.key === k);
    if (meta?.required) return;
    const next = new Set(visible);
    if (next.has(k)) next.delete(k); else next.add(k);
    setVisible(next);
  };
  const reset = () => {
    setVisible(new Set(COL_META.filter((c) => c.defaultOn).map((c) => c.key)));
  };
  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen((v) => !v)}
              data-testid="biz-clients-columns-btn"
              aria-haspopup="true" aria-expanded={open}
              className="prosper-btn-ghost h-9 text-xs gap-1.5">
        <Columns3 size={13} /> Columnas
        <span className="font-mono text-[10px] text-fg-subtle">({visible.size}/{COL_META.length})</span>
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1.5 w-56 z-30 prosper-card p-1.5
                       shadow-card-hover animate-fade-in"
             data-testid="biz-clients-columns-menu">
          <div className="px-2 py-1.5 flex items-center justify-between">
            <span className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
              Columnas visibles
            </span>
            <button onClick={reset}
                    data-testid="biz-clients-columns-reset"
                    className="text-[10px] font-mono uppercase tracking-wider
                               text-fg-subtle hover:text-fg">
              reset
            </button>
          </div>
          <div className="max-h-72 overflow-y-auto">
            {COL_META.map((c) => {
              const on = visible.has(c.key);
              return (
                <button key={c.key}
                  onClick={() => toggle(c.key)}
                  data-testid={`biz-clients-col-${c.key}`}
                  disabled={c.required}
                  aria-pressed={on}
                  className={cn(
                    "w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs",
                    "hover:bg-surface-hover transition-colors text-left",
                    c.required && "opacity-60 cursor-not-allowed",
                  )}>
                  <span className={cn("w-3.5 h-3.5 rounded-sm border flex items-center justify-center",
                    on ? "bg-primary border-primary" : "border-border")}>
                    {on && <Check size={10} className="text-white" />}
                  </span>
                  <span className="flex-1">{c.label}</span>
                  {c.required && (
                    <span className="text-[9px] font-mono text-fg-subtle uppercase">req</span>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
