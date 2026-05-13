"use client";
import { useState } from "react";
import { PageHeader, Badge, DataTable, type Column } from "@prosper/ui";
import { toast } from "sonner";
import { Search, Plus, Settings2 } from "lucide-react";
import {
  useKytRules, patchKytRule, useKytAlerts, useWatchlist, addWatchlist,
  screenWallet, useTravelRule,
  type KytRule, type KytAlert, type WatchlistEntry, type TravelRuleRow,
} from "@/lib/admin-compliance";
import { cn, fmtDate, fmtMoney } from "@/lib/utils";

type Tab = "rules" | "alerts" | "onchain" | "travel";
const TABS: { id: Tab; label: string }[] = [
  { id: "rules",   label: "Reglas configurables" },
  { id: "alerts",  label: "Alertas KYT" },
  { id: "onchain", label: "Análisis on-chain" },
  { id: "travel",  label: "Travel rule" },
];
const SEV_TONE: Record<string, "info" | "warning" | "danger"> = {
  info: "info", warning: "warning", critical: "danger",
};

export default function KytPage() {
  const [tab, setTab] = useState<Tab>("rules");
  return (
    <div data-testid="compl-kyt-page">
      <PageHeader
        breadcrumbs={[{ label: "Admin", href: "/admin" },
                      { label: "Compliance", href: "/admin/compliance" },
                      { label: "KYT" }]}
        kicker="Phase 5 · Compliance"
        title="KYT · Transaction Monitoring"
        subtitle="Reglas de monitoreo, alertas generadas, análisis on-chain y travel rule." />
      <div className="flex border-b border-border mb-5" data-testid="kyt-tabs">
        {TABS.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)}
            data-testid={`kyt-tab-${t.id}`}
            className={cn("px-4 py-2.5 text-xs font-mono uppercase tracking-wider transition-colors border-b-2 -mb-px",
              tab === t.id
                ? "border-primary text-fg"
                : "border-transparent text-fg-subtle hover:text-fg")}>
            {t.label}
          </button>
        ))}
      </div>
      {tab === "rules"   && <RulesTab />}
      {tab === "alerts"  && <AlertsTab />}
      {tab === "onchain" && <OnchainTab />}
      {tab === "travel"  && <TravelTab />}
    </div>
  );
}

function RulesTab() {
  const swr = useKytRules();
  const items = swr.data?.items ?? [];
  const onToggle = async (r: KytRule, enabled: boolean) => {
    try { await patchKytRule(r.rule_id, { enabled }); await swr.mutate();
          toast.success(`${r.name} ${enabled ? "ON" : "OFF"}`); }
    catch (e: any) { toast.error(e?.message || "Failed"); }
  };
  const onParam = async (r: KytRule, value: string) => {
    const v = isNaN(Number(value)) ? value : Number(value);
    try { await patchKytRule(r.rule_id, { param_value: v }); await swr.mutate(); toast.success("Updated"); }
    catch (e: any) { toast.error(e?.message || "Failed"); }
  };
  const onSev = async (r: KytRule, s: KytRule["severity"]) => {
    try { await patchKytRule(r.rule_id, { severity: s }); await swr.mutate(); toast.success("Severity"); }
    catch (e: any) { toast.error(e?.message || "Failed"); }
  };
  return (
    <div className="space-y-2" data-testid="kyt-rules-list">
      {items.map((r) => (
        <div key={r.rule_id}
             data-testid={`kyt-rule-${r.rule_id}`}
             className="prosper-card p-4 flex flex-wrap items-center gap-4">
          <div className="min-w-[240px] flex-1">
            <div className="flex items-center gap-2">
              <span className="font-display font-bold text-sm">{r.name}</span>
              <Badge size="sm" tone={SEV_TONE[r.severity]}>{r.severity}</Badge>
            </div>
            <p className="text-[11px] text-fg-subtle mt-0.5">{r.description}</p>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <span className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
              {r.param_name}
            </span>
            <input defaultValue={String(r.param_value)}
              onBlur={(e) => e.target.value !== String(r.param_value) && onParam(r, e.target.value)}
              data-testid={`kyt-rule-param-${r.rule_id}`}
              className="w-32 px-2 py-1.5 rounded border border-border bg-surface
                         font-mono text-xs focus:outline-none focus:border-primary" />
            <span className="text-[10px] font-mono text-fg-subtle">{r.param_unit}</span>
          </div>
          <select value={r.severity} onChange={(e) => onSev(r, e.target.value as KytRule["severity"])}
            data-testid={`kyt-rule-severity-${r.rule_id}`}
            className="px-2 py-1.5 rounded border border-border bg-surface font-mono text-xs">
            <option value="info">info</option>
            <option value="warning">warning</option>
            <option value="critical">critical</option>
          </select>
          <label className="inline-flex items-center cursor-pointer"
                 data-testid={`kyt-rule-toggle-${r.rule_id}`}>
            <input type="checkbox" checked={r.enabled}
              onChange={(e) => onToggle(r, e.target.checked)}
              className="sr-only peer" />
            <div className="relative w-10 h-5 bg-surface-hover rounded-full
                            peer-checked:bg-primary peer-focus:ring-2 peer-focus:ring-primary/30
                            after:content-[''] after:absolute after:top-0.5 after:left-0.5
                            after:bg-white after:rounded-full after:h-4 after:w-4
                            after:transition-all peer-checked:after:translate-x-5"/>
          </label>
        </div>
      ))}
    </div>
  );
}

function AlertsTab() {
  const swr = useKytAlerts();
  const cols: Column<KytAlert>[] = [
    { key: "created_at", header: "Cuando", width: "130px",
      render: (r) => <span className="font-mono text-[11px]">{fmtDate(r.created_at)}</span> },
    { key: "prosper_tx_id", header: "TX", width: "120px",
      render: (r) => <a href={`/admin/operations/transactions/${r.tx_id}`}
        target="_blank" rel="noreferrer"
        className="font-mono text-[11px] text-primary hover:underline">
        {r.prosper_tx_id || r.tx_id?.slice(0, 10)}</a> },
    { key: "org_name", header: "Cliente",
      render: (r) => <span className="text-fg">{r.org_name || r.org_id?.slice(0, 14) || "—"}</span> },
    { key: "rule_name", header: "Regla",
      render: (r) => <span className="text-[11px]">{r.rule_name}</span> },
    { key: "amount", header: "Monto", numeric: true, width: "120px", align: "right",
      render: (r) => <span className="font-mono tabular">{fmtMoney(r.amount)}</span> },
    { key: "score", header: "Score", numeric: true, width: "70px", align: "right",
      render: (r) => <span className="font-mono tabular">{r.score}</span> },
    { key: "severity", header: "Severity", width: "100px",
      render: (r) => <Badge size="sm" tone={SEV_TONE[r.severity]}>{r.severity}</Badge> },
    { key: "status", header: "Status", width: "120px",
      render: (r) => <Badge size="sm"
        tone={r.status === "resolved" ? "success" : r.status === "acknowledged" ? "info" : "warning"}>
        {r.status}</Badge> },
  ];
  return (
    <DataTable<KytAlert>
      data={swr.data?.items ?? []} columns={cols}
      rowKey={(r) => r.alert_id}
      empty={swr.isLoading ? "Loading…" : "No KYT alerts"} />
  );
}

function OnchainTab() {
  const wl = useWatchlist();
  const [addr, setAddr] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<any>(null);
  const [newWl, setNewWl] = useState({ value: "", reason: "" });

  const check = async () => {
    if (!addr.trim()) return;
    setBusy(true);
    try { setRes(await screenWallet(addr.trim())); }
    catch (e: any) { toast.error(e?.message || "Screen failed"); }
    finally { setBusy(false); }
  };
  const add = async () => {
    if (!newWl.value.trim() || !newWl.reason.trim()) {
      toast.error("Wallet + motivo required"); return;
    }
    try { await addWatchlist({ kind: "wallet", value: newWl.value.trim(),
                                reason: newWl.reason.trim() });
          setNewWl({ value: "", reason: "" }); await wl.mutate();
          toast.success("Added"); }
    catch (e: any) { toast.error(e?.message || "Add failed"); }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6" data-testid="kyt-onchain">
      <div className="prosper-card p-5" data-testid="onchain-screen">
        <h3 className="font-display font-bold text-sm mb-3">Check wallet (TRM Labs)</h3>
        <div className="flex gap-2">
          <input value={addr} onChange={(e) => setAddr(e.target.value)}
            placeholder="GA…/0x… address"
            data-testid="onchain-input"
            className="flex-1 px-3 py-2 rounded border border-border bg-surface
                       font-mono text-xs focus:outline-none focus:border-primary"/>
          <button onClick={check} disabled={busy || !addr.trim()}
            data-testid="onchain-check"
            className="prosper-btn-primary h-9 text-xs gap-1.5 disabled:opacity-50">
            <Search size={13}/> {busy ? "…" : "Check"}
          </button>
        </div>
        {res && (
          <div className="mt-4 text-xs font-mono space-y-1" data-testid="onchain-result">
            <div>Internal watchlist: {res.internal_watchlist_hit
              ? <Badge tone="danger" size="sm">HIT</Badge>
              : <Badge tone="success" size="sm">clear</Badge>}</div>
            <div>External screening (TRM): <Badge tone={
              res.external.status === "success" ? "success" :
              res.external.status === "unavailable" ? "warning" : "danger"
            } size="sm">{res.external.status}</Badge>
              {res.external.error_reason && <span className="text-fg-subtle ml-2">{res.external.error_reason}</span>}
            </div>
            {res.external.risk_score != null && (
              <div>Risk score: <span className="text-fg">{res.external.risk_score}</span></div>
            )}
            {res.external.is_sanctioned && (
              <div><Badge tone="danger">SANCTIONED</Badge></div>
            )}
          </div>
        )}
      </div>

      <div className="prosper-card p-5" data-testid="onchain-watchlist">
        <h3 className="font-display font-bold text-sm mb-3">Watchlist interna</h3>
        <div className="flex flex-col gap-2 mb-3">
          <input value={newWl.value} onChange={(e) => setNewWl({ ...newWl, value: e.target.value })}
            placeholder="Wallet address"
            data-testid="watchlist-value"
            className="px-3 py-2 rounded border border-border bg-surface font-mono text-xs
                       focus:outline-none focus:border-primary"/>
          <input value={newWl.reason} onChange={(e) => setNewWl({ ...newWl, reason: e.target.value })}
            placeholder="Motivo"
            data-testid="watchlist-reason"
            className="px-3 py-2 rounded border border-border bg-surface text-xs
                       focus:outline-none focus:border-primary"/>
          <button onClick={add} data-testid="watchlist-add"
            className="prosper-btn-primary h-9 text-xs gap-1.5 self-end">
            <Plus size={13}/> Add to watchlist
          </button>
        </div>
        <div className="border-t border-border pt-3 max-h-72 overflow-y-auto space-y-2">
          {(wl.data?.items ?? []).map((e) => (
            <div key={e.entry_id} className="text-[11px] font-mono"
                 data-testid={`watchlist-row-${e.entry_id}`}>
              <Badge tone={e.kind === "wallet" ? "warning" : "info"} size="sm">{e.kind}</Badge>
              <span className="ml-2 truncate inline-block max-w-[260px] align-middle">{e.value}</span>
              <div className="text-fg-subtle mt-0.5">{e.reason}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function TravelTab() {
  const swr = useTravelRule();
  const cols: Column<TravelRuleRow>[] = [
    { key: "created_at", header: "When", width: "150px",
      render: (r) => <span className="font-mono text-[11px]">{fmtDate(r.created_at)}</span> },
    { key: "prosper_tx_id", header: "TX",
      render: (r) => <span className="font-mono text-[11px]">{r.prosper_tx_id || r.tx_id}</span> },
    { key: "amount", header: "Amount", numeric: true, width: "120px", align: "right",
      render: (r) => <span className="font-mono tabular">{fmtMoney(r.amount)}</span> },
    { key: "counterparty_name", header: "Counterparty",
      render: (r) => r.counterparty_name || <span className="text-fg-subtle">—</span> },
    { key: "travel_rule_status", header: "Travel rule", width: "120px",
      render: (r) => <Badge size="sm"
        tone={r.travel_rule_status === "verified" ? "success" : "danger"}>
        {r.travel_rule_status}</Badge> },
  ];
  return (
    <DataTable<TravelRuleRow>
      data={swr.data?.items ?? []} columns={cols}
      rowKey={(r) => r.tx_id}
      empty={swr.isLoading ? "Loading…" : "No travel-rule txs"} />
  );
}
