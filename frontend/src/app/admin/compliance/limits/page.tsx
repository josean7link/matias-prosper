"use client";
import { useState } from "react";
import { useTranslations } from "next-intl";
import { PageHeader, Badge, DataTable, type Column } from "@prosper/ui";
import { History as HistoryIcon } from "lucide-react";
import { toast } from "sonner";
import { useLimits, patchLimit, useLimitsHistory, type LimitRow } from "@/lib/admin-compliance";
import { cn, fmtMoney, fmtDate } from "@/lib/utils";

type CapKey = "subscribe_daily_cap_usd" | "subscribe_monthly_cap_usd"
            | "redeem_daily_cap_usd"    | "redeem_monthly_cap_usd";

export default function LimitsPage() {
  const tH = useTranslations("admin.headers");
  const tA = useTranslations("admin");
  const swr = useLimits();
  const [historyOrg, setHistoryOrg] = useState<string | null>(null);

  const onSave = async (orgId: string, key: CapKey, value: number) => {
    try { await patchLimit(orgId, key, value); await swr.mutate(); toast.success("Cap updated"); }
    catch (e: any) { toast.error(e?.message || "Patch failed"); }
  };

  const cols: Column<LimitRow>[] = [
    { key: "name", header: "Cliente", sortable: true,
      render: (r) => <span className="text-fg">{r.name}</span> },
    { key: "type", header: "Tipo", width: "120px",
      render: (r) => <Badge tone="auto" size="sm">{r.type || "—"}</Badge> },
    { key: "subscribe_daily_cap_usd", header: "Subscribe / day", numeric: true,
      width: "150px", align: "right",
      render: (r) => <CapCell row={r} k="subscribe_daily_cap_usd" onSave={onSave} /> },
    { key: "subscribe_monthly_cap_usd", header: "Subscribe / month", numeric: true,
      width: "160px", align: "right",
      render: (r) => <CapCell row={r} k="subscribe_monthly_cap_usd" onSave={onSave} /> },
    { key: "redeem_daily_cap_usd", header: "Redeem / day", numeric: true,
      width: "150px", align: "right",
      render: (r) => <CapCell row={r} k="redeem_daily_cap_usd" onSave={onSave} /> },
    { key: "redeem_monthly_cap_usd", header: "Redeem / month", numeric: true,
      width: "160px", align: "right",
      render: (r) => <CapCell row={r} k="redeem_monthly_cap_usd" onSave={onSave} /> },
    { key: "org_id", header: "", width: "60px",
      render: (r) => (
        <button onClick={() => setHistoryOrg(r.org_id)}
          data-testid={`limits-history-${r.org_id}`}
          className="prosper-btn-ghost h-7 px-2 text-[10px] gap-1">
          <HistoryIcon size={11}/> hist
        </button>) },
  ];

  return (
    <div data-testid="compl-limits-page">
      <PageHeader
        breadcrumbs={[{ label: tA("breadcrumb_admin"), href: "/admin" },
                      { label: tH("comp_label"), href: "/admin/compliance" },
                      { label: tH("comp_limits_bc") }]}
        kicker={tH("comp_limits_kicker")}
        title={tH("comp_limits_title")}
        subtitle={tH("comp_limits_subtitle")} />
      <DataTable<LimitRow>
        data={swr.data?.items ?? []} columns={cols}
        rowKey={(r) => r.org_id}
        empty={swr.isLoading ? "Loading…" : "No limits"} />
      {historyOrg && <HistoryDrawer orgId={historyOrg} onClose={() => setHistoryOrg(null)} />}
    </div>
  );
}

function CapCell({ row, k, onSave }:
  { row: LimitRow; k: CapKey; onSave: (orgId: string, k: CapKey, v: number) => void }) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(String(row[k]));
  if (!editing) return (
    <button onClick={() => { setEditing(true); setVal(String(row[k])); }}
      data-testid={`cap-${row.org_id}-${k}`}
      className="font-mono tabular text-xs px-2 py-1 rounded hover:bg-surface-hover w-full text-right">
      {fmtMoney(row[k])}
    </button>
  );
  const submit = () => {
    const n = Number(val);
    if (!Number.isFinite(n) || n < 0) { toast.error("Número inválido"); setEditing(false); return; }
    setEditing(false);
    if (n !== row[k]) onSave(row.org_id, k, n);
  };
  return (
    <input type="number" autoFocus value={val}
      onChange={(e) => setVal(e.target.value)}
      onBlur={submit}
      onKeyDown={(e) => { if (e.key === "Enter") submit();
                          if (e.key === "Escape") setEditing(false); }}
      data-testid={`cap-input-${row.org_id}-${k}`}
      className="w-full px-2 py-1 rounded border border-primary bg-surface
                 font-mono tabular text-xs text-right focus:outline-none" />
  );
}

function HistoryDrawer({ orgId, onClose }: { orgId: string; onClose: () => void }) {
  const swr = useLimitsHistory(orgId);
  return (
    <div className="fixed inset-0 z-40 flex" data-testid="limits-history-drawer">
      <div className="flex-1 bg-black/40 backdrop-blur-sm" onClick={onClose}/>
      <div className="w-full max-w-[520px] bg-bg border-l border-border h-full overflow-y-auto p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-display font-bold text-lg">Historial de cambios</h2>
          <button onClick={onClose} className="prosper-btn-ghost h-8 px-3 text-xs">Close</button>
        </div>
        <div className="text-[10px] font-mono text-fg-subtle mb-3">org {orgId}</div>
        <ol className="border-l border-border pl-4 space-y-3">
          {(swr.data?.items ?? []).map((h, i) => (
            <li key={i} className="text-xs" data-testid={`limit-hist-${i}`}>
              <div className="font-mono text-[10px] text-fg-subtle">{fmtDate(h.changed_at)}</div>
              <div className="text-fg mt-0.5">
                <span className="font-mono text-fg-subtle">{h.key}</span>
                <span className="font-mono text-fg-subtle"> · </span>
                <span className="font-mono line-through text-fg-subtle">{fmtMoney(h.old_value)}</span>
                <span className="font-mono mx-1.5">→</span>
                <span className="font-mono text-success">{fmtMoney(h.new_value)}</span>
              </div>
              <div className="text-[10px] text-fg-subtle font-mono mt-0.5">by {h.changed_by}</div>
            </li>
          ))}
          {(swr.data?.items ?? []).length === 0 && !swr.isLoading && (
            <li className="text-fg-subtle text-xs">No changes yet</li>
          )}
        </ol>
      </div>
    </div>
  );
}
