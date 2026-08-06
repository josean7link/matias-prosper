"use client";
import { useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { PageHeader, Badge, DataTable, type Column } from "@prosper/ui";
import { Plus, Search, AlertCircle, RefreshCw, Users, Pause, Sparkles } from "lucide-react";
import { useClients, type ClientRow } from "@/lib/admin-clients";
import { api } from "@/lib/api";
import { cn, fmtMoney, fmtDate } from "@/lib/utils";

const KYB_TONE: Record<string, "success" | "info" | "warning" | "danger" | "auto"> = {
  approved:  "success", pending: "warning", in_review: "info",
  rejected:  "danger",  needs_info: "warning", paused: "warning",
};
const TYPE_OPTS = ["fintech", "broker", "family_office", "retail_aggregator", "other"];
const ENV_OPTS  = ["sandbox", "production"];
const KYB_OPTS  = ["pending", "in_review", "approved", "rejected", "paused", "needs_info"];

export default function ClientsListPage() {
  const t = useTranslations("admin.clients_page");
  const tBase = useTranslations("admin");
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
    { key: "legal_name", header: t("col_client"), sortable: true,
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
    { key: "country", header: t("col_country"), width: "70px",
      render: (r) => <span className="font-mono text-[11px]">{r.country}</span> },
    { key: "type", header: t("col_type"), width: "120px",
      render: (r) => <Badge tone="auto" size="sm">{r.type}</Badge> },
    { key: "env", header: t("col_env"), width: "100px",
      render: (r) => <Badge tone={r.env === "production" ? "danger" : "warning"} size="sm">{r.env}</Badge> },
    { key: "kyb_status", header: t("col_kyb"), width: "120px",
      render: (r) => (
        <div className="flex items-center gap-1.5">
          <Badge tone={KYB_TONE[r.kyb_status] || "auto"} size="sm">{r.kyb_status}</Badge>
          {r.kyb_refresh_due && (
            <span title={t("kyb_refresh_due")}
                  className="text-warning"><RefreshCw size={11}/></span>
          )}
          {r.paused && <Pause size={11} className="text-warning"/>}
        </div>) },
    { key: "users_count", header: "", numeric: true, width: "60px", align: "right",
      render: (r) => (
        <span className="font-mono tabular text-[11px] inline-flex items-center gap-1 text-fg-muted">
          <Users size={11}/>{r.users_count}
        </span>) },
    { key: "volume_total", header: t("col_volume"), numeric: true, sortable: true,
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
    { key: "created_at", header: t("col_created"), width: "130px",
      render: (r) => <span className="font-mono text-[11px]">{fmtDate(r.created_at)}</span> },
  ];

  return (
    <div data-testid="admin-clients-list-page">
      <PageHeader
        breadcrumbs={[{ label: tBase("breadcrumb_admin"), href: "/admin" }, { label: t("breadcrumb") }]}
        kicker={t("kicker")}
        title={t("title")}
        subtitle={t("subtitle")}
        actions={
          <div className="flex items-center gap-2">
            <button
              data-testid="clients-seed-demo-btn"
              onClick={async () => {
                if (!window.confirm(t("seed_confirm"))) return;
                try {
                  const r = await api<{ ok: true; org_id: string; legal_name?: string }>(
                    "/v1/admin/ops/seed-demo-client",
                    { method: "POST",
                      body: JSON.stringify({ auto_approve: true, seed_history: true }) });
                  toast.success(t("seed_success", { orgId: r.org_id }));
                  swr.mutate();
                } catch (err) {
                  toast.error((err as Error).message || t("seed_error"));
                }
              }}
              className="prosper-btn-ghost h-9 text-xs gap-1.5">
              <Sparkles size={13}/> {t("seed_demo")}
            </button>
            <Link href="/admin/clients/new"
              data-testid="clients-new-btn"
              className="prosper-btn-primary h-9 text-xs gap-1.5">
              <Plus size={13}/> {t("new_client")}
            </Link>
          </div>
        }
      />

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2 mb-3" data-testid="clients-filters">
        <div className="flex items-center gap-1.5 flex-1 min-w-[200px] max-w-md
                        bg-surface border border-border rounded h-9 px-2.5">
          <Search size={12} className="text-fg-subtle"/>
          <input value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }}
            placeholder={t("search_placeholder")}
            data-testid="clients-search"
            className="flex-1 bg-transparent outline-none text-xs"/>
        </div>
        <FilterGroup label={t("filter_kyb")}  opts={KYB_OPTS}  value={kyb}  setValue={setKyb}  testid="kyb"/>
        <FilterGroup label={t("filter_type")} opts={TYPE_OPTS} value={type} setValue={setType} testid="type"/>
        <FilterGroup label={t("filter_env")}  opts={ENV_OPTS}  value={env}  setValue={setEnv}  testid="env"/>
      </div>

      <DataTable<ClientRow>
        data={items} columns={cols} rowKey={(r) => r.org_id}
        empty={swr.isLoading ? t("loading") : t("empty")}/>

      <div className="flex items-center justify-between mt-3 text-[11px] font-mono text-fg-subtle">
        <div>
          {t("footer_count", { total, page, totalPages })}
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}
            data-testid="clients-prev"
            className="prosper-btn-ghost h-7 px-2 text-[10px] disabled:opacity-30">{t("pagination_prev")}</button>
          <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            data-testid="clients-next"
            className="prosper-btn-ghost h-7 px-2 text-[10px] disabled:opacity-30">{t("pagination_next")}</button>
          <select value={pageSize}
            onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}
            data-testid="clients-page-size"
            className="bg-surface border border-border rounded px-1.5 py-0.5 text-[10px] font-mono">
            <option value={25}>25</option>
            <option value={50}>50</option>
            <option value={100}>100</option>
            <option value={500}>{t("pagination_all")}</option>
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
