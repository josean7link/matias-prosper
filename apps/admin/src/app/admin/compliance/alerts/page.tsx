"use client";
import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { PageHeader, Badge, DataTable, type Column } from "@prosper/ui";
import { toast } from "sonner";
import { useAlerts, patchAlert, bulkPatchAlerts, type AlertItem } from "@/lib/admin-compliance";
import { cn, fmtDate } from "@/lib/utils";

const SEV_TONE: Record<string, "info" | "warning" | "danger"> = {
  info: "info", warning: "warning", critical: "danger",
};

export default function AlertsPage() {
  const tH = useTranslations("admin.headers");
  const tA = useTranslations("admin");
  const [sev,    setSev]    = useState<string[]>([]);
  const [type,   setType]   = useState<string[]>([]);
  const [status, setStatus] = useState<string[]>([]);
  const swr = useAlerts({
    severity: sev.length ? sev : undefined,
    type:     type.length ? type : undefined,
    status:   status.length ? status : undefined,
  });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const items = swr.data?.items ?? [];
  const allSelected = items.length > 0 && selected.size === items.length;

  const onBulk = async (s: "acknowledged" | "resolved") => {
    if (selected.size === 0) { toast.error("Nada seleccionado"); return; }
    try { await bulkPatchAlerts({ alert_ids: Array.from(selected), status: s });
          await swr.mutate(); setSelected(new Set());
          toast.success(`${s} ${selected.size} alertas`); }
    catch (e: any) { toast.error(e?.message || "Bulk failed"); }
  };

  const cols: Column<AlertItem>[] = [
    { key: "alert_id", header: "", width: "40px",
      render: (r) => (
        <input type="checkbox" checked={selected.has(r.alert_id)}
          onClick={(e) => e.stopPropagation()}
          onChange={(e) => {
            const next = new Set(selected);
            if (e.target.checked) next.add(r.alert_id); else next.delete(r.alert_id);
            setSelected(next);
          }}
          data-testid={`alert-cb-${r.alert_id}`} />) },
    { key: "severity", header: "Severity", width: "110px",
      render: (r) => <Badge tone={SEV_TONE[r.severity]} size="sm"
                            data-testid={`alert-sev-${r.alert_id}`}>{r.severity}</Badge> },
    { key: "type", header: "Type", width: "110px",
      render: (r) => <Badge tone="auto" size="sm">{r.type}</Badge> },
    { key: "title", header: "Title",
      render: (r) => (<div>
        <div className="text-fg text-xs">{r.title}</div>
        <div className="text-[10px] text-fg-subtle font-mono">{r.description}</div>
      </div>) },
    { key: "org_name", header: "Cliente", width: "150px",
      render: (r) => r.org_name || (r.org_id ? r.org_id.slice(0, 18) : "—") },
    { key: "status", header: "Status", width: "110px",
      render: (r) => <Badge size="sm"
        tone={r.status === "resolved" ? "success" : r.status === "acknowledged" ? "info" : "warning"}>
        {r.status}</Badge> },
    { key: "created_at", header: "Edad", width: "140px",
      render: (r) => <span className="font-mono text-[11px]">{fmtDate(r.created_at)}</span> },
  ];

  return (
    <div data-testid="compl-alerts-page">
      <PageHeader
        breadcrumbs={[{ label: tA("breadcrumb_admin"), href: "/admin" },
                      { label: tH("comp_label"), href: "/admin/compliance" },
                      { label: tH("comp_alerts_bc") }]}
        kicker={tH("comp_alerts_kicker")}
        title={tH("comp_alerts_title")}
        subtitle={tH("comp_alerts_subtitle")} />

      {/* Filter chips */}
      <div className="flex flex-wrap gap-2 mb-3" data-testid="alerts-filters">
        <FilterGroup label="Severity" all={["info","warning","critical"]}
          value={sev} setValue={setSev} testid="sev" />
        <FilterGroup label="Type" all={["kyt","operational","compliance","technical"]}
          value={type} setValue={setType} testid="type" />
        <FilterGroup label="Status" all={["open","acknowledged","resolved"]}
          value={status} setValue={setStatus} testid="status" />
      </div>

      {/* Bulk actions */}
      <div className="flex items-center justify-between mb-3">
        <div className="text-[11px] font-mono text-fg-subtle">
          {selected.size} seleccionadas
          {selected.size > 0 && (
            <button onClick={() => setSelected(new Set())}
              className="ml-2 underline">clear</button>
          )}
        </div>
        <div className="flex gap-2">
          <button onClick={() => onBulk("acknowledged")} disabled={selected.size === 0}
            data-testid="bulk-ack"
            className="prosper-btn-ghost h-8 text-xs disabled:opacity-50">Acknowledge</button>
          <button onClick={() => onBulk("resolved")} disabled={selected.size === 0}
            data-testid="bulk-resolve"
            className="prosper-btn-primary h-8 text-xs disabled:opacity-50">Resolve</button>
        </div>
      </div>

      <DataTable<AlertItem>
        data={items} columns={cols}
        rowKey={(r) => r.alert_id}
        empty={swr.isLoading ? "Loading…" : "No alerts"} />
    </div>
  );
}

function FilterGroup({ label, all, value, setValue, testid }:
  { label: string; all: string[]; value: string[];
    setValue: (v: string[]) => void; testid: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mr-1">{label}</span>
      {all.map((s) => {
        const active = value.includes(s);
        return (
          <button key={s}
            onClick={() => setValue(active ? value.filter((x) => x !== s) : [...value, s])}
            data-testid={`alerts-chip-${testid}-${s}`}
            className={cn("h-7 px-2.5 rounded-full text-[10px] font-mono uppercase tracking-wider",
              active ? "bg-fg text-bg"
                     : "bg-surface text-fg-muted hover:text-fg border border-border")}>
            {s}
          </button>
        );
      })}
    </div>
  );
}
