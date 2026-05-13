"use client";
import { useState } from "react";
import Link from "next/link";
import { PageHeader, Badge, DataTable, type Column } from "@prosper/ui";
import { Plus, Search, AlertCircle, RefreshCw, Users, Pause } from "lucide-react";
import { useClients, type ClientRow } from "@/lib/admin-clients";
import { cn, fmtMoney, fmtDate } from "@/lib/utils";

const KYB_TONE: Record<string, "success" | "info" | "warning" | "danger" | "auto"> = {
  approved:  "success", pending: "warning", in_review: "info",
  rejected:  "danger",  needs_info: "warning", paused: "warning",
};
const TYPE_OPTS = ["fintech", "broker", "family_office", "retail_aggregator", "other"];
const ENV_OPTS  = ["sandbox", "production"];
const KYB_OPTS  = ["pending", "in_review", "approved", "rejected", "paused", "needs_info"];

export default function ClientsListPage() {
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [kyb, setKyb]   = useState<string[]>([]);
  const [type, setType] = useState<string[]>([]);
  const [env, setEnv]   = useState<string[]>([]);
  const swr = useClients({
    kyb_status: kyb.length ? kyb : undefined,
    type:       type.length ? type : undefined,
    env:        env.length ? env : undefined,
    q: q || undefined, page, page_size: pageSize,
  });
  const items = swr.data?.items ?? [];
  const total = swr.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const cols: Column<ClientRow>[] = [
    { key: "legal_name", header: "Cliente", sortable: true,
      render: (r) => (
        <Link href={`/admin/clients/${r.org_id}`} className="flex items-center gap-2.5 group">
          <div className="w-7 h-7 rounded-full bg-primary/10 text-primary
                          flex items-center justify-center font-display font-bold text-[10px]">
            {(r.commercial_name || r.legal_name).slice(0, 2).toUpperCase()}
          </div>
          <div>
            <div className="text-fg group-hover:text-primary">{r.legal_name}</div>
            <div className="text-[10px] text-fg-subtle font-mono">{r.tax_id} · {r.primary_email}</div>
          </div>
        </Link>) },
    { key: "country", header: "País", width: "70px",
      render: (r) => <span className="font-mono text-[11px]">{r.country}</span> },
    { key: "type", header: "Tipo", width: "120px",
      render: (r) => <Badge tone="auto" size="sm">{r.type}</Badge> },
    { key: "env", header: "Env", width: "100px",
      render: (r) => <Badge tone={r.env === "production" ? "danger" : "warning"} size="sm">{r.env}</Badge> },
    { key: "kyb_status", header: "KYB", width: "120px",
      render: (r) => (
        <div className="flex items-center gap-1.5">
          <Badge tone={KYB_TONE[r.kyb_status] || "auto"} size="sm">{r.kyb_status}</Badge>
          {r.kyb_refresh_due && (
            <span title="KYB refresh due"
                  className="text-warning"><RefreshCw size={11}/></span>
          )}
          {r.paused && <Pause size={11} className="text-warning"/>}
        </div>) },
    { key: "users_count", header: "", numeric: true, width: "60px", align: "right",
      render: (r) => (
        <span className="font-mono tabular text-[11px] inline-flex items-center gap-1 text-fg-muted">
          <Users size={11}/>{r.users_count}
        </span>) },
    { key: "volume_total", header: "Volumen", numeric: true, sortable: true,
      width: "140px", align: "right",
      render: (r) => <span className="font-mono tabular">{fmtMoney(r.volume_total)}</span> },
    { key: "critical_alerts", header: "", width: "80px",
      render: (r) => r.critical_alerts > 0 ? (
        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-danger/10 text-danger
                         text-[10px] font-mono uppercase tracking-wider"
              data-testid={`client-alerts-${r.org_id}`}>
          <AlertCircle size={10}/>{r.critical_alerts}
        </span>
      ) : <span className="text-fg-subtle text-[10px]">—</span> },
    { key: "created_at", header: "Alta", width: "130px",
      render: (r) => <span className="font-mono text-[11px]">{fmtDate(r.created_at)}</span> },
  ];

  return (
    <div data-testid="admin-clients-list-page">
      <PageHeader
        breadcrumbs={[{ label: "Admin", href: "/admin" }, { label: "Clientes" }]}
        kicker="Phase 6"
        title="Clientes"
        subtitle="Organizaciones registradas en Prosper · onboarding, accesos, API keys, webhooks."
        actions={
          <Link href="/admin/clients/new"
            data-testid="clients-new-btn"
            className="prosper-btn-primary h-9 text-xs gap-1.5">
            <Plus size={13}/> Nuevo cliente
          </Link>
        }
      />

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2 mb-3" data-testid="clients-filters">
        <div className="flex items-center gap-1.5 flex-1 min-w-[200px] max-w-md
                        bg-surface border border-border rounded h-9 px-2.5">
          <Search size={12} className="text-fg-subtle"/>
          <input value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }}
            placeholder="Buscar por nombre, tax id o email…"
            data-testid="clients-search"
            className="flex-1 bg-transparent outline-none text-xs"/>
        </div>
        <FilterGroup label="KYB"  opts={KYB_OPTS}  value={kyb}  setValue={setKyb}  testid="kyb"/>
        <FilterGroup label="Tipo" opts={TYPE_OPTS} value={type} setValue={setType} testid="type"/>
        <FilterGroup label="Env"  opts={ENV_OPTS}  value={env}  setValue={setEnv}  testid="env"/>
      </div>

      <DataTable<ClientRow>
        data={items} columns={cols} rowKey={(r) => r.org_id}
        empty={swr.isLoading ? "Loading…" : "No clients match the filter"}/>

      <div className="flex items-center justify-between mt-3 text-[11px] font-mono text-fg-subtle">
        <div>
          {total} clientes · página {page} de {totalPages}
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}
            data-testid="clients-prev"
            className="prosper-btn-ghost h-7 px-2 text-[10px] disabled:opacity-30">prev</button>
          <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            data-testid="clients-next"
            className="prosper-btn-ghost h-7 px-2 text-[10px] disabled:opacity-30">next</button>
          <select value={pageSize}
            onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}
            data-testid="clients-page-size"
            className="bg-surface border border-border rounded px-1.5 py-0.5 text-[10px] font-mono">
            <option value={25}>25</option>
            <option value={50}>50</option>
            <option value={100}>100</option>
            <option value={500}>all</option>
          </select>
        </div>
      </div>
    </div>
  );
}

function FilterGroup({ label, opts, value, setValue, testid }:
  { label: string; opts: string[]; value: string[];
    setValue: (v: string[]) => void; testid: string }) {
  return (
    <div className="flex items-center gap-1">
      <span className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle px-1">{label}</span>
      {opts.map((o) => {
        const on = value.includes(o);
        return (
          <button key={o} onClick={() =>
              setValue(on ? value.filter((x) => x !== o) : [...value, o])}
            data-testid={`clients-chip-${testid}-${o}`}
            className={cn("h-7 px-2.5 rounded-full text-[10px] font-mono uppercase tracking-wider",
              on ? "bg-fg text-bg"
                 : "bg-surface text-fg-muted hover:text-fg border border-border")}>
            {o}
          </button>
        );
      })}
    </div>
  );
}
