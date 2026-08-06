"use client";
/**
 * Phase 22 + P1-3 (Feb 2026) — Backoffice monitor: /admin/prosper/inversiones.
 *
 * Five sections on the same screen:
 *   - CMS Treasury widget + Staking sync status (always visible at top)
 *   - Stakings (CMS live):  ours (by org) + external/historical residue.
 *   - Intents (legacy):     bridge intents — read-only, deprecated.
 *   - Positions:            active/matured/redeemed positions, asset-aware.
 *   - Trustlines:           per-org missing-trustline monitor.
 *
 * CSV export for intents. Numbers in IBM Plex Mono.
 */
import { useState } from "react";
import useSWR, { mutate as globalMutate } from "swr";
import {
  AlertTriangle, CheckCircle2, Download, ExternalLink, Filter,
  Loader2, RefreshCw, XCircle, Zap,
} from "lucide-react";
import { toast } from "sonner";
import { PageHeader, Badge } from "@prosper/ui";
import { api } from "@/lib/api";

type Tab = "stakings" | "intents" | "positions" | "trustlines";

interface Intent {
  id: string; org_id: string; end_customer_id?: string;
  direction: "in" | "out"; source?: string;
  step: string;
  amount_arsa?: number; amount_usdc?: number;
  prosper_tx_id?: string; andes_transfer_id?: string;
  position_id?: string | null;
  fail_reason?: string | null;
  is_stuck?: boolean;
  created_at: string; updated_at: string;
}

interface Position {
  position_id: string; org_id: string; end_customer_id?: string;
  product_id: string; asset?: string; display_currency?: string;
  principal_usd: number; accrued_interest: number;
  apr_bps: number; status: string;
  start: string; maturity?: string | null;
}

interface TrustlineRow {
  org_id: string; name: string; stellar_address?: string;
  trustlines: { asset: string; issuer: string; established_at?: string }[];
  missing: string[]; ok: boolean;
}

export default function ProsperInversionesMonitor() {
  const [tab, setTab] = useState<Tab>("stakings");
  return (
    <div data-testid="prosper-monitor-page">
      <PageHeader
        breadcrumbs={[{ label: "Admin", href: "/admin" },
                       { label: "Prosper", href: "/admin/prosper/productos" },
                       { label: "Inversiones" }]}
        kicker="CMS protocol · Monitor de stakings on-chain"
        title="Inversiones · monitor operativo"
        subtitle="Stakings vivos (CMS), intents históricos (bridge deprecated), posiciones por org y trustlines."/>

      {/* Treasury + sync widget — always visible at the top */}
      <CmsHeaderWidgets />

      {/* Tabs */}
      <div className="flex items-center gap-2 mb-5 border-b border-border"
            data-testid="prosper-monitor-tabs">
        {(["stakings", "intents", "positions", "trustlines"] as Tab[]).map((t) => (
          <button key={t} onClick={() => setTab(t)}
                   data-testid={`prosper-monitor-tab-${t}`}
                   className={"h-10 px-4 text-xs font-mono uppercase tracking-wider " +
                     (tab === t ? "text-fg border-b-2 border-fg -mb-px"
                                 : "text-fg-muted hover:text-fg")}>
            {t === "stakings" ? "Stakings (CMS live)"
             : t === "intents" ? "Intents (legacy)"
             : t}
          </button>
        ))}
      </div>

      {tab === "stakings"   && <StakingsTab/>}
      {tab === "intents"    && <IntentsTab/>}
      {tab === "positions"  && <PositionsTab/>}
      {tab === "trustlines" && <TrustlinesTab/>}
    </div>
  );
}

// ===========================================================================
// Intents tab
// ===========================================================================
function IntentsTab() {
  const [stepFilter, setStepFilter] = useState<string>("");
  const [directionF, setDirectionF] = useState<string>("");
  const qs = new URLSearchParams();
  if (stepFilter) qs.set("step", stepFilter);
  if (directionF) qs.set("direction", directionF);
  qs.set("stuck_minutes", "15");
  qs.set("limit", "200");

  const { data, mutate, isLoading } = useSWR<{
    items: Intent[]; total: number; stuck_count: number; failed_count: number;
  }>(`/v1/admin/prosper/intents?${qs.toString()}`,
     (p: string) => api(p), { refreshInterval: 4000 });

  const items = data?.items ?? [];

  const action = async (id: string, act: "retry" | "mark_failed", reason?: string) => {
    try {
      await api(`/v1/admin/prosper/intents/${id}/action`, {
        method: "POST",
        body: JSON.stringify({ action: act, reason }),
      });
      toast.success(act === "retry" ? "Reintento registrado" : "Marcado como failed");
      mutate();
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  const downloadCsv = () => {
    const url = `${process.env.NEXT_PUBLIC_API || ""}/api/v1/admin/prosper/intents.csv?${qs.toString()}`;
    window.open(url, "_blank");
  };

  return (
    <>
      {/* KPIs */}
      <div className="grid grid-cols-3 gap-4 mb-5">
        <Kpi label="Total intents" value={data?.total ?? 0}
              tone="neutral" testid="intents-kpi-total"/>
        <Kpi label="Trabados (>15m)" value={data?.stuck_count ?? 0}
              tone={(data?.stuck_count ?? 0) > 0 ? "warning" : "neutral"}
              testid="intents-kpi-stuck"/>
        <Kpi label="Failed" value={data?.failed_count ?? 0}
              tone={(data?.failed_count ?? 0) > 0 ? "danger" : "neutral"}
              testid="intents-kpi-failed"/>
      </div>

      {/* Filter bar */}
      <div className="prosper-card p-3 mb-4 flex items-center gap-2 flex-wrap"
            data-testid="intents-filter-bar">
        <span className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
          <Filter size={12} className="inline mr-1"/> filtros
        </span>
        <select value={directionF} onChange={(e) => setDirectionF(e.target.value)}
                 className="h-7 px-2 text-xs rounded border border-border bg-surface"
                 data-testid="intents-filter-direction">
          <option value="">Todas las direcciones</option>
          <option value="in">Cash IN</option>
          <option value="out">Cash OUT</option>
        </select>
        <select value={stepFilter} onChange={(e) => setStepFilter(e.target.value)}
                 className="h-7 px-2 text-xs rounded border border-border bg-surface"
                 data-testid="intents-filter-step">
          <option value="">Todos los steps</option>
          <option value="converting">Converting</option>
          <option value="bridging">Bridging</option>
          <option value="subscribing">Subscribing</option>
          <option value="active">Active</option>
          <option value="redeeming">Redeeming</option>
          <option value="reconverting">Reconverting</option>
          <option value="paid_out">Paid out</option>
          <option value="failed">Failed</option>
        </select>
        <div className="ml-auto flex gap-1">
          <button onClick={() => mutate()}
                   className="h-7 px-2 rounded border border-border text-xs hover:bg-surface"
                   data-testid="intents-refresh">
            <RefreshCw size={12} className="inline mr-1"/> refresh
          </button>
          <button onClick={downloadCsv}
                   className="h-7 px-2 rounded border border-border text-xs hover:bg-surface"
                   data-testid="intents-export-csv">
            <Download size={12} className="inline mr-1"/> CSV
          </button>
        </div>
      </div>

      {/* Table */}
      <div className="prosper-card overflow-hidden" data-testid="intents-table">
        <table className="w-full text-sm">
          <thead className="bg-surface text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
            <tr>
              <th className="text-left px-3 py-2">Step</th>
              <th className="text-left px-3 py-2">Dir</th>
              <th className="text-left px-3 py-2">Org / Person</th>
              <th className="text-right px-3 py-2">Monto</th>
              <th className="text-left px-3 py-2">Prosper TX</th>
              <th className="text-left px-3 py-2">Andes TX</th>
              <th className="text-right px-3 py-2">Updated</th>
              <th className="text-right px-3 py-2">Acciones</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr><td colSpan={8} className="text-center py-8 text-fg-subtle">
                <Loader2 size={16} className="animate-spin inline"/></td></tr>
            )}
            {!isLoading && items.length === 0 && (
              <tr><td colSpan={8} className="text-center py-8 text-fg-subtle text-xs">
                Sin intents.</td></tr>
            )}
            {items.map((i) => {
              const stuck   = i.is_stuck;
              const failed  = i.step === "failed";
              const amount  = i.amount_arsa
                ? `$ ${Number(i.amount_arsa).toLocaleString("es-AR")} ARSa`
                : i.amount_usdc
                  ? `${Number(i.amount_usdc).toFixed(2)} USDC`
                  : "—";
              return (
                <tr key={i.id}
                     data-testid={`intent-row-${i.id}`}
                     data-stuck={stuck ? "1" : "0"}
                     className={"border-t border-border " +
                       (failed ? "bg-danger/5" :
                        stuck  ? "bg-warning/5" : "")}>
                  <td className="px-3 py-2">
                    <Badge tone={
                      i.step === "active" || i.step === "paid_out" ? "success" :
                      failed ? "danger" :
                      stuck  ? "warning" : "info"} size="sm">
                      {i.step}
                    </Badge>
                  </td>
                  <td className="px-3 py-2 font-mono text-xs uppercase">
                    {i.direction}
                  </td>
                  <td className="px-3 py-2">
                    <div className="font-mono text-[11px]">{i.org_id}</div>
                    {i.end_customer_id && (
                      <div className="text-[10px] text-fg-subtle font-mono">
                        {i.end_customer_id}
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums">{amount}</td>
                  <td className="px-3 py-2 font-mono text-[11px] text-fg-muted">
                    {i.prosper_tx_id?.slice(0, 16) || "—"}…
                  </td>
                  <td className="px-3 py-2 font-mono text-[11px] text-fg-muted">
                    {i.andes_transfer_id?.slice(0, 12) || "—"}
                  </td>
                  <td className="px-3 py-2 text-right text-[10px] font-mono text-fg-subtle">
                    {new Date(i.updated_at).toLocaleString("es-AR", {
                      hour12: false, day: "2-digit", month: "short",
                      hour: "2-digit", minute: "2-digit" })}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {(stuck || failed) && (
                      <div className="flex justify-end gap-1">
                        <button
                          onClick={() => action(i.id, "retry")}
                          data-testid={`intent-action-retry-${i.id}`}
                          className="h-6 px-2 text-[10px] rounded border border-border hover:bg-surface gap-1 inline-flex items-center">
                          <Zap size={10}/> retry
                        </button>
                        {!failed && (
                          <button
                            onClick={() => {
                              const reason = prompt("Motivo del mark_failed:");
                              if (reason) action(i.id, "mark_failed", reason);
                            }}
                            data-testid={`intent-action-mark-failed-${i.id}`}
                            className="h-6 px-2 text-[10px] rounded border border-danger/30 text-danger hover:bg-danger/5 gap-1 inline-flex items-center">
                            <XCircle size={10}/> fail
                          </button>
                        )}
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

// ===========================================================================
// Positions tab
// ===========================================================================
function PositionsTab() {
  const [assetF, setAssetF] = useState<string>("");
  const [statusF, setStatusF] = useState<string>("");
  const qs = new URLSearchParams();
  if (assetF)  qs.set("asset",  assetF);
  if (statusF) qs.set("status", statusF);
  qs.set("limit", "500");

  const { data } = useSWR<{ items: Position[]; total: number }>(
    `/v1/admin/prosper/positions?${qs.toString()}`,
    (p: string) => api(p));

  return (
    <>
      <div className="prosper-card p-3 mb-4 flex items-center gap-2">
        <span className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
          <Filter size={12} className="inline mr-1"/> filtros
        </span>
        <select value={assetF} onChange={(e) => setAssetF(e.target.value)}
                 className="h-7 px-2 text-xs rounded border border-border bg-surface"
                 data-testid="positions-filter-asset">
          <option value="">Todos los assets</option>
          <option value="usdc">USDC</option>
          <option value="arsa">ARSa</option>
        </select>
        <select value={statusF} onChange={(e) => setStatusF(e.target.value)}
                 className="h-7 px-2 text-xs rounded border border-border bg-surface"
                 data-testid="positions-filter-status">
          <option value="">Todos los estados</option>
          <option value="active">Active</option>
          <option value="matured">Matured</option>
          <option value="redeemed">Redeemed</option>
        </select>
      </div>
      <div className="prosper-card overflow-hidden" data-testid="positions-table">
        <table className="w-full text-sm">
          <thead className="bg-surface text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
            <tr>
              <th className="text-left px-3 py-2">Position</th>
              <th className="text-left px-3 py-2">Org</th>
              <th className="text-left px-3 py-2">Person</th>
              <th className="text-left px-3 py-2">Product</th>
              <th className="text-left px-3 py-2">Asset</th>
              <th className="text-right px-3 py-2">Principal</th>
              <th className="text-right px-3 py-2">Accrued</th>
              <th className="text-right px-3 py-2">APR</th>
              <th className="text-center px-3 py-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {data?.items.map((p) => (
              <tr key={p.position_id}
                   className="border-t border-border"
                   data-testid={`position-row-${p.position_id}`}>
                <td className="px-3 py-2 font-mono text-[11px]">{p.position_id}</td>
                <td className="px-3 py-2 font-mono text-[11px]">{p.org_id}</td>
                <td className="px-3 py-2 font-mono text-[11px] text-fg-muted">
                  {p.end_customer_id || "—"}
                </td>
                <td className="px-3 py-2 text-xs">{p.product_id}</td>
                <td className="px-3 py-2">
                  <Badge tone={p.asset === "arsa" ? "warning" : "info"} size="sm">
                    {p.display_currency || (p.asset || "usdc").toUpperCase()}
                  </Badge>
                </td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">
                  {p.principal_usd.toFixed(2)}
                </td>
                <td className="px-3 py-2 text-right font-mono tabular-nums text-success">
                  {p.accrued_interest.toFixed(6)}
                </td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">
                  {(p.apr_bps / 100).toFixed(2)}%
                </td>
                <td className="px-3 py-2 text-center">
                  <Badge tone={p.status === "active" ? "success" :
                                p.status === "redeemed" ? "neutral" : "info"} size="sm">
                    {p.status}
                  </Badge>
                </td>
              </tr>
            )) || null}
            {!data?.items.length && (
              <tr><td colSpan={9} className="text-center py-8 text-fg-subtle text-xs">
                Sin posiciones.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

// ===========================================================================
// Trustlines tab
// ===========================================================================
function TrustlinesTab() {
  const { data, mutate } = useSWR<{
    items: TrustlineRow[]; total: number; missing_count: number;
  }>(`/v1/admin/prosper/trustlines`, (p: string) => api(p));
  const force = async (orgId: string, asset: string) => {
    try {
      await api(`/v1/admin/prosper/accounts/${orgId}/trustline`, {
        method: "POST", body: JSON.stringify({ asset }),
      });
      toast.success(`Trustline ${asset} forzada para ${orgId}`);
      mutate();
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  return (
    <>
      <div className="grid grid-cols-2 gap-4 mb-5">
        <Kpi label="Orgs con wallet Prosper" value={data?.total ?? 0}
              tone="neutral" testid="trustlines-kpi-total"/>
        <Kpi label="Con trustlines faltantes"
              value={data?.missing_count ?? 0}
              tone={(data?.missing_count ?? 0) > 0 ? "warning" : "success"}
              testid="trustlines-kpi-missing"/>
      </div>
      <div className="prosper-card overflow-hidden" data-testid="trustlines-table">
        <table className="w-full text-sm">
          <thead className="bg-surface text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
            <tr>
              <th className="text-left px-3 py-2">Org</th>
              <th className="text-left px-3 py-2">Wallet</th>
              <th className="text-left px-3 py-2">Establecidos</th>
              <th className="text-left px-3 py-2">Faltantes</th>
              <th className="text-right px-3 py-2">Acciones</th>
            </tr>
          </thead>
          <tbody>
            {data?.items.map((row) => (
              <tr key={row.org_id} className="border-t border-border"
                   data-testid={`trustline-row-${row.org_id}`}>
                <td className="px-3 py-2">
                  <div className="font-display font-bold text-sm">{row.name}</div>
                  <div className="font-mono text-[10px] text-fg-subtle">{row.org_id}</div>
                </td>
                <td className="px-3 py-2 font-mono text-[10px] text-fg-muted">
                  {row.stellar_address?.slice(0, 10) || "—"}…
                </td>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap gap-1">
                    {row.trustlines.map((t) => (
                      <Badge key={t.asset} tone="success" size="sm">
                        <CheckCircle2 size={9}/> {t.asset}
                      </Badge>
                    ))}
                  </div>
                </td>
                <td className="px-3 py-2">
                  {row.missing.length === 0
                    ? <span className="text-[10px] text-fg-subtle">—</span>
                    : (
                      <div className="flex flex-wrap gap-1">
                        {row.missing.map((m) => (
                          <Badge key={m} tone="warning" size="sm">
                            <AlertTriangle size={9}/> {m}
                          </Badge>
                        ))}
                      </div>
                    )}
                </td>
                <td className="px-3 py-2 text-right">
                  {row.missing.map((m) => (
                    <button key={m} onClick={() => force(row.org_id, m)}
                             data-testid={`trustline-force-${row.org_id}-${m}`}
                             className="h-7 px-2 text-[10px] rounded border border-border hover:bg-surface gap-1 inline-flex items-center">
                      <Zap size={10}/> ensure {m}
                    </button>
                  ))}
                </td>
              </tr>
            )) || null}
            {!data?.items.length && (
              <tr><td colSpan={5} className="text-center py-8 text-fg-subtle text-xs">
                Sin orgs con wallet Prosper aún.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

// ===========================================================================
// Shared KPI card
// ===========================================================================
function Kpi({ label, value, tone, testid }:
  { label: string; value: number;
    tone: "neutral" | "success" | "warning" | "danger";
    testid?: string; }) {
  const color = tone === "danger"  ? "text-danger"
              : tone === "warning" ? "text-warning"
              : tone === "success" ? "text-success" : "text-fg";
  return (
    <div className="prosper-card p-4" data-testid={testid}>
      <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">{label}</div>
      <div className={"font-display text-3xl font-bold mt-1 tabular-nums " + color}>
        {value.toLocaleString("es-AR")}
      </div>
    </div>
  );
}



// ===========================================================================
// CMS LIVE — Treasury widget + Staking sync run widget
// ===========================================================================
interface Treasury {
  address: string | null;
  balanceUSDC: string | number | null;
  balanceARSA: string | number | null;
  balanceXLM:  string | number | null;
  mode: string;
  refreshed_at: string;
}

interface SyncRun {
  ok: boolean;
  processed: number;
  created: number;
  updated: number;
  external_total: number;
  external_created: number;
  external_updated: number;
  skipped: number;
  elapsed_seconds: number;
  started_at: string;
  finished_at: string;
}

interface SyncStatus {
  enabled: boolean;
  mode: string;
  interval_minutes: number;
  last_run: SyncRun | null;
}

function CmsHeaderWidgets() {
  const { data: t, error: tErr, mutate: mutT } =
    useSWR<Treasury>("/v1/admin/prosper/treasury",
                      (p: string) => api(p));
  const { data: s, mutate: mutS } =
    useSWR<SyncStatus>("/v1/admin/prosper/staking-sync/status",
                        (p: string) => api(p),
      { refreshInterval: 60_000 });

  const [running, setRunning] = useState(false);
  const runNow = async () => {
    setRunning(true);
    try {
      await api<SyncRun>("/v1/admin/prosper/staking-sync/run",
                          { method: "POST" });
      toast.success("Staking sync ejecutado");
      mutS(); mutT();
      globalMutate("/v1/admin/prosper/stakings?scope=all");
    } catch (e) {
      toast.error((e as Error).message || "Sync falló");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6"
         data-testid="cms-header-widgets">
      {/* Treasury card */}
      <div className="prosper-card p-4 lg:col-span-2" data-testid="cms-treasury-card">
        <div className="flex items-center justify-between mb-3">
          <div>
            <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
              CMS Treasury · live
            </div>
            <h3 className="font-display font-bold text-base text-fg">
              Treasury del protocolo
            </h3>
          </div>
          <button onClick={() => mutT()} title="Refrescar"
                  className="prosper-btn-ghost h-8 px-3 text-xs gap-1"
                  data-testid="cms-treasury-refresh">
            <RefreshCw size={12}/> Refrescar
          </button>
        </div>
        {tErr ? (
          <div className="text-xs text-danger">No se pudo leer /cms/treasury — verificá credenciales partner.</div>
        ) : !t ? (
          <div className="text-xs text-fg-subtle">Cargando…</div>
        ) : (
          <div className="grid grid-cols-3 gap-3">
            <TreasuryCell label="balanceUSDC" value={t.balanceUSDC} unit="USDC"
                          testid="cms-treasury-usdc"/>
            <TreasuryCell label="balanceARSA" value={t.balanceARSA} unit="ARSa"
                          testid="cms-treasury-arsa"/>
            <TreasuryCell label="balanceXLM" value={t.balanceXLM} unit="XLM"
                          testid="cms-treasury-xlm"/>
            <div className="col-span-3 text-[10px] font-mono text-fg-subtle pt-1 flex items-center justify-between border-t border-border mt-1">
              <span>
                Address:{" "}
                {t.address ? (
                  <a href={`https://stellar.expert/explorer/public/account/${t.address}`}
                     target="_blank" rel="noopener noreferrer"
                     className="text-primary hover:underline">
                    {t.address.slice(0,6)}…{t.address.slice(-6)}
                  </a>
                ) : "—"}
              </span>
              <span>
                mode={t.mode} · {new Date(t.refreshed_at).toLocaleTimeString("es-AR")}
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Staking sync widget */}
      <div className="prosper-card p-4" data-testid="cms-sync-widget">
        <div className="flex items-start justify-between mb-3">
          <div>
            <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
              Staking sync · poller
            </div>
            <h3 className="font-display font-bold text-base text-fg">Última corrida</h3>
          </div>
          <span className={"text-[10px] font-mono px-2 h-5 rounded-full inline-flex items-center " +
                  (s?.enabled ? "bg-success/10 text-success" : "bg-fg-muted/10 text-fg-muted")}>
            {s?.enabled ? "ENABLED" : "DISABLED"}
          </span>
        </div>
        {!s?.last_run ? (
          <div className="text-xs text-fg-subtle">Aún no corrió. Hacé click en "Run now".</div>
        ) : (
          <div className="space-y-1.5">
            <SyncMetric label="Processed" value={s.last_run.processed} />
            <SyncMetric label="Created (nuestros)" value={s.last_run.created} tone="success"/>
            <SyncMetric label="Updated (nuestros)" value={s.last_run.updated} tone="info"/>
            <SyncMetric label="External (residuo)" value={s.last_run.external_total} tone="muted"/>
            <div className="text-[10px] font-mono text-fg-subtle pt-1 border-t border-border">
              {new Date(s.last_run.finished_at).toLocaleString("es-AR")} ·{" "}
              {s.last_run.elapsed_seconds.toFixed(2)}s · cada {s.interval_minutes}m
            </div>
          </div>
        )}
        <button onClick={runNow} disabled={running}
                className="prosper-btn-primary w-full h-9 mt-3 text-xs gap-1.5"
                data-testid="cms-sync-run-now">
          {running ? <><Loader2 size={12} className="animate-spin"/> Ejecutando…</>
                    : <><Zap size={12}/> Run now</>}
        </button>
      </div>
    </div>
  );
}

function TreasuryCell({ label, value, unit, testid }:
  { label: string; value: string | number | null; unit: string; testid: string }) {
  const v = value == null ? "—" : Number(value).toLocaleString("es-AR",
    { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return (
    <div data-testid={testid}>
      <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
        {label}
      </div>
      <div className="font-display text-xl font-bold tabular-nums text-fg">
        {v} <span className="text-[10px] font-mono text-fg-subtle">{unit}</span>
      </div>
    </div>
  );
}

function SyncMetric({ label, value, tone }:
  { label: string; value: number; tone?: "success" | "info" | "muted" }) {
  const color = tone === "success" ? "text-success"
              : tone === "info"    ? "text-primary"
              : tone === "muted"   ? "text-fg-muted" : "text-fg";
  return (
    <div className="flex items-center justify-between text-xs">
      <span className="text-fg-muted">{label}</span>
      <span className={"font-mono tabular-nums font-semibold " + color}>{value}</span>
    </div>
  );
}

// ===========================================================================
// STAKINGS (CMS live) tab — ours + external
// ===========================================================================
interface CmsStaking {
  position_id: string;
  org_id: string | null;
  external?: boolean;
  asset: "arsa" | "usdc";
  modality: "end" | "month";
  wallet: string;
  memo: string;
  hash: string;
  rate: number;
  principal_native: number;
  principal_unit: string;
  status: "active" | "matured" | "redeemed";
  start?: string;
  maturity?: string;
  contract_email?: string;
  contract_id?: string;
  contract_provides_interest?: boolean;
  accrued_interest?: number;
  claimed_interest?: number;
  principal_redeemed?: number;
  updated_at?: string;
}

interface CmsStakingsResp {
  ours: {
    items: CmsStaking[];
    by_org: Array<{ org_id: string; name: string;
                     positions: CmsStaking[];
                     principal_arsa: number; principal_usdc: number;
                     active_count: number; }>;
    total: number;
  };
  external: { items: CmsStaking[]; total: number; note: string };
  total: number;
  fetched_at: string;
}

function StakingsTab() {
  const [scope, setScope] = useState<"all" | "ours" | "external">("all");
  const [asset, setAsset] = useState<"" | "arsa" | "usdc">("");
  const [status, setStatus] = useState<"" | "active" | "matured" | "redeemed">("");
  const qs = new URLSearchParams();
  qs.set("scope", scope);
  if (asset) qs.set("asset", asset);
  if (status) qs.set("status", status);
  const { data, isLoading, mutate } = useSWR<CmsStakingsResp>(
    `/v1/admin/prosper/stakings?${qs.toString()}`,
    (p: string) => api(p),
    { refreshInterval: 60_000 });

  return (
    <div data-testid="cms-stakings-tab" className="space-y-6">
      {/* Filter bar */}
      <div className="prosper-card p-3 flex flex-wrap items-center gap-3">
        <Filter size={14} className="text-fg-subtle" />
        <Select label="Scope" value={scope} onChange={(v) => setScope(v as "all" | "ours" | "external")}
                options={[
                  { value: "all",      label: "Todos" },
                  { value: "ours",     label: "Nuestros" },
                  { value: "external", label: "Externos" }]}
                testid="cms-filter-scope" />
        <Select label="Asset" value={asset} onChange={(v) => setAsset(v as "" | "arsa" | "usdc")}
                options={[{ value: "", label: "Todos" },
                            { value: "arsa", label: "ARSa" },
                            { value: "usdc", label: "USDC" }]}
                testid="cms-filter-asset" />
        <Select label="Estado" value={status}
                onChange={(v) => setStatus(v as "" | "active" | "matured" | "redeemed")}
                options={[{ value: "", label: "Todos" },
                            { value: "active", label: "Activo" },
                            { value: "matured", label: "Maduro" },
                            { value: "redeemed", label: "Redimido" }]}
                testid="cms-filter-status" />
        <button onClick={() => mutate()}
                className="prosper-btn-ghost h-8 px-3 text-xs gap-1 ml-auto"
                data-testid="cms-stakings-refresh">
          <RefreshCw size={12}/> Refrescar
        </button>
      </div>

      {isLoading && <div className="text-xs text-fg-subtle py-4">Cargando…</div>}

      {/* OURS — by org */}
      {data && (scope === "all" || scope === "ours") && (
        <section data-testid="cms-stakings-ours">
          <SectionHeader title="Nuestros stakings"
            count={data.ours.total}
            description="Stakings on-chain en wallets que nosotros provisionamos." />
          {data.ours.total === 0 ? (
            <div className="prosper-card p-6 text-center text-xs text-fg-subtle">
              No hay stakings propios en el CMS todavía. Cuando un cliente transfiera
              fondos a una wallet provisionada, aparecerán acá automáticamente.
            </div>
          ) : (
            <div className="space-y-4">
              {data.ours.by_org.map((g) => (
                <div key={g.org_id} className="prosper-card p-4"
                     data-testid={`cms-stakings-org-${g.org_id}`}>
                  <div className="flex items-center justify-between mb-3">
                    <div>
                      <div className="font-display font-bold text-sm text-fg">{g.name}</div>
                      <div className="text-[10px] font-mono text-fg-subtle">{g.org_id}</div>
                    </div>
                    <div className="flex items-center gap-2 text-[11px] font-mono">
                      {g.principal_usdc > 0 && (
                        <Badge tone="info">{g.principal_usdc.toLocaleString("es-AR")} USDC</Badge>)}
                      {g.principal_arsa > 0 && (
                        <Badge tone="success">{g.principal_arsa.toLocaleString("es-AR")} ARSa</Badge>)}
                      <span className="text-fg-subtle">· {g.active_count} activos</span>
                    </div>
                  </div>
                  <StakingTable items={g.positions} external={false} />
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {/* EXTERNAL — historic residue */}
      {data && (scope === "all" || scope === "external") && (
        <section data-testid="cms-stakings-external">
          <SectionHeader title="Externos / históricos"
            count={data.external.total}
            tone="muted"
            description={data.external.note} />
          {data.external.total === 0 ? (
            <div className="prosper-card p-6 text-center text-xs text-fg-subtle">
              Sin stakings externos.
            </div>
          ) : (
            <div className="prosper-card p-0 overflow-hidden">
              <StakingTable items={data.external.items} external={true} />
            </div>
          )}
        </section>
      )}
    </div>
  );
}

function SectionHeader({ title, count, description, tone }:
  { title: string; count: number; description: string;
    tone?: "muted" }) {
  return (
    <div className="flex items-start justify-between mb-3">
      <div>
        <h3 className={"font-display font-bold text-base " +
                       (tone === "muted" ? "text-fg-muted" : "text-fg")}>
          {title}{" "}
          <span className="text-fg-subtle text-sm font-mono font-normal">
            ({count})
          </span>
        </h3>
        <p className="text-[11px] text-fg-muted mt-0.5 max-w-3xl">{description}</p>
      </div>
    </div>
  );
}

function StakingTable({ items, external }:
  { items: CmsStaking[]; external: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle border-b border-border">
          <tr className="text-left">
            <th className="px-3 py-2">Asset</th>
            <th className="px-3 py-2">Modalidad</th>
            <th className="px-3 py-2 text-right">Principal</th>
            <th className="px-3 py-2 text-right">Rate</th>
            <th className="px-3 py-2">Status</th>
            <th className="px-3 py-2">Memo</th>
            <th className="px-3 py-2">Hash</th>
            <th className="px-3 py-2">Vence</th>
            {external && <th className="px-3 py-2">Origen</th>}
          </tr>
        </thead>
        <tbody className="font-mono">
          {items.map((p) => (
            <tr key={p.position_id}
                className={"border-b border-border last:border-b-0 " +
                  (external ? "opacity-70" : "hover:bg-surface-hover")}>
              <td className="px-3 py-2 uppercase text-fg">{p.asset}</td>
              <td className="px-3 py-2">
                <Badge tone={p.modality === "end" ? "info" : "warning"} size="sm">
                  {p.modality}
                </Badge>
              </td>
              <td className="px-3 py-2 text-right tabular-nums text-fg">
                {p.principal_native.toLocaleString("es-AR")}{" "}
                <span className="text-fg-subtle">{p.principal_unit}</span>
              </td>
              <td className="px-3 py-2 text-right tabular-nums">{p.rate}%</td>
              <td className="px-3 py-2">
                <Badge tone={p.status === "active" ? "success"
                              : p.status === "matured" ? "warning" : "neutral"} size="sm">
                  {p.status}
                </Badge>
              </td>
              <td className="px-3 py-2 text-fg-muted">{p.memo}</td>
              <td className="px-3 py-2">
                <a href={`https://stellar.expert/explorer/public/tx/${p.hash}`}
                   target="_blank" rel="noopener noreferrer"
                   className="text-primary hover:underline inline-flex items-center gap-1">
                  {p.hash.slice(0, 6)}…{p.hash.slice(-4)}
                  <ExternalLink size={10} />
                </a>
              </td>
              <td className="px-3 py-2 text-fg-muted">
                {p.maturity ? p.maturity.slice(0, 10) : "—"}
              </td>
              {external && (
                <td className="px-3 py-2 text-fg-subtle">
                  {p.contract_email || "—"}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Select({ label, value, onChange, options, testid }:
  { label: string; value: string; onChange: (v: string) => void;
    options: { value: string; label: string }[]; testid: string }) {
  return (
    <label className="flex items-center gap-2 text-[11px] font-mono text-fg-muted">
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)}
              data-testid={testid}
              className="prosper-input h-8 text-xs px-2">
        {options.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
      </select>
    </label>
  );
}
