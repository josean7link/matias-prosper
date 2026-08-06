"use client";
import { useState } from "react";
import { useTranslations } from "next-intl";
import { Badge, PageHeader } from "@prosper/ui";
import { Download, Search, AlertTriangle, RefreshCw, XCircle, Wrench } from "lucide-react";
import { toast } from "sonner";
import {
  useAdminMovements, fmtArsaAdmin, type AdminMovement,
  useStuckMovements, resyncMovement, markMovementFailed,
  type StuckMovement,
} from "@/lib/admin-ramp";

/** Phase 16 · C — /admin/rampa/movimientos */
export default function RampMovementsAdminPage() {
  const tH = useTranslations("admin.headers");
  const tA = useTranslations("admin");
  const [kind, setKind]       = useState("");
  const [status, setStatus]   = useState("");
  const [q, setQ]             = useState("");
  const [from, setFrom]       = useState("");
  const [to, setTo]           = useState("");
  const filters = {
    ...(kind ? { kind } : {}),
    ...(status ? { status } : {}),
    ...(q ? { q } : {}),
    ...(from ? { date_from: from } : {}),
    ...(to ? { date_to: to } : {}),
    limit: "200",
  };
  const qs = "?" + new URLSearchParams(filters).toString();
  const list = useAdminMovements(qs);

  const exportCsv = () => {
    const u = `/api/v1/admin/ramp/movements.csv?${new URLSearchParams(
      { ...filters, limit: "20000" }).toString()}`;
    window.location.href = u;
  };

  return (
    <div className="space-y-6">
      <PageHeader
        crumbs={[{ label: tA("breadcrumb_admin") }, { label: tH("rampa_label") },
                  { label: tH("rampa_movs_bc") }]}
        title={tH("rampa_movs_title")}
        subtitle={tH("rampa_movs_subtitle")}
        actions={
          <button onClick={exportCsv}
                  data-testid="ramp-movements-export-csv"
                  className="prosper-btn-ghost h-9 text-xs gap-1.5">
            <Download size={12}/> Exportar CSV
          </button>
        }
      />

      {/* Filters */}
      <StuckPanel/>

      <section className="prosper-card p-4 flex flex-wrap items-end gap-3"
               data-testid="ramp-movements-filters">
        <div className="flex-1 min-w-[220px]">
          <span className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
            Búsqueda
          </span>
          <div className="relative mt-1">
            <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-subtle"/>
            <input
              value={q} onChange={e => setQ(e.target.value)}
              placeholder="ext_id · CVU · destino · prosper_tx"
              data-testid="ramp-mov-search"
              className="w-full pl-7 pr-3 h-9 rounded border border-border bg-bg text-fg text-sm font-mono focus:outline-none focus:border-primary"/>
          </div>
        </div>
        <Sel label="Tipo" value={kind} onChange={setKind}
              testid="ramp-mov-filter-kind"
              opts={[["", "todos"],["deposit","deposit"],["withdrawal","withdrawal"],
                      ["transfer","transfer"],["intl_offramp","intl_offramp"]]}/>
        <Sel label="Estado" value={status} onChange={setStatus}
              testid="ramp-mov-filter-status"
              opts={[["", "todos"],["Success","Success"],["Pending","Pending"],
                      ["TransferPending","TransferPending"],["Failed","Failed"]]}/>
        <DateField label="Desde" value={from} onChange={setFrom}
                    testid="ramp-mov-filter-from"/>
        <DateField label="Hasta" value={to} onChange={setTo}
                    testid="ramp-mov-filter-to"/>
        <button onClick={() => list.mutate()}
                className="prosper-btn-ghost h-9 text-xs gap-1.5">
          <RefreshCw size={11} className={list.isLoading ? "animate-spin" : ""}/>
          Actualizar
        </button>
      </section>

      <section className="prosper-card overflow-x-auto"
               data-testid="ramp-movements-table">
        <table className="w-full text-xs">
          <thead className="bg-surface border-b border-border">
            <tr className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
              <th className="text-left  py-2 px-3">Fecha</th>
              <th className="text-left  py-2 px-3">Tipo · asset</th>
              <th className="text-left  py-2 px-3">Estado</th>
              <th className="text-right py-2 px-3">Monto</th>
              <th className="text-left  py-2 px-3">Destino</th>
              <th className="text-left  py-2 px-3">prosper_tx / ext</th>
            </tr>
          </thead>
          <tbody>
            {list.isLoading && (
              <tr><td colSpan={6} className="py-4 text-center italic text-fg-subtle">
                Cargando…</td></tr>
            )}
            {!list.isLoading && (list.data?.items.length ?? 0) === 0 && (
              <tr><td colSpan={6} className="py-6 text-center text-fg-subtle">
                Sin movimientos</td></tr>
            )}
            {(list.data?.items || []).map(m => (
              <MovRow key={m.id} m={m}/>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function MovRow({ m }: { m: AdminMovement }) {
  const fail = m.status === "Failed";
  const stale = m.is_stale;
  const rowCls = fail
    ? "bg-danger/5 hover:bg-danger/10"
    : stale
      ? "bg-warning/5 hover:bg-warning/10"
      : "hover:bg-surface/50";
  return (
    <tr className={`border-b border-border/40 ${rowCls}`}
        data-testid={`ramp-mov-row-${m.id}`}>
      <td className="py-2 px-3 font-mono text-[10px] text-fg-muted">
        {new Date(m.created_at).toLocaleString()}
        {m.settled_at && <div className="text-fg-subtle">→ {new Date(m.settled_at).toLocaleTimeString()}</div>}
      </td>
      <td className="py-2 px-3">
        <div className="text-fg font-display font-semibold capitalize">{m.kind}</div>
        <div className="text-[10px] font-mono text-fg-subtle">
          {m.asset === "arsa" ? "ARSa" : m.asset.toUpperCase()} · {m.chain}
        </div>
      </td>
      <td className="py-2 px-3">
        <Badge tone={m.status === "Success" ? "success"
                      : m.status === "Failed" ? "danger" : "warning"}>
          {m.status}
        </Badge>
        {stale && (
          <div className="text-[10px] text-warning mt-0.5 flex items-center gap-0.5">
            <AlertTriangle size={9}/> &gt;30 min sin settle
          </div>
        )}
        {m.fail_reason && (
          <div className="text-[10px] text-danger mt-0.5 max-w-[220px] truncate"
               title={m.fail_reason}>
            {m.fail_reason}
          </div>
        )}
      </td>
      <td className="py-2 px-3 text-right font-mono tabular text-fg">
        {m.kind === "deposit" ? "+" : "−"} {fmtArsaAdmin(m.amount)}
      </td>
      <td className="py-2 px-3 font-mono text-[10px]">
        {m.destination_name && <div className="text-fg">{m.destination_name}</div>}
        {m.destination_cvu && <div className="text-fg-subtle">{m.destination_cvu}</div>}
        {!m.destination_name && !m.destination_cvu && <span className="text-fg-subtle italic">—</span>}
      </td>
      <td className="py-2 px-3 font-mono text-[10px]">
        {m.prosper_tx_id && <div className="text-fg">{m.prosper_tx_id}</div>}
        {m.external_id && <div className="text-fg-subtle">↔ {m.external_id}</div>}
      </td>
    </tr>
  );
}

function Sel({ label, value, onChange, opts, testid }: {
  label: string; value: string; onChange: (v: string) => void;
  opts: [string, string][]; testid?: string;
}) {
  return (
    <label className="block">
      <span className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
        {label}
      </span>
      <select value={value} onChange={e => onChange(e.target.value)}
              data-testid={testid}
              className="mt-1 px-2.5 h-9 rounded border border-border bg-bg text-fg text-sm font-mono focus:outline-none focus:border-primary">
        {opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
}
function DateField({ label, value, onChange, testid }: {
  label: string; value: string; onChange: (v: string) => void; testid?: string;
}) {
  return (
    <label className="block">
      <span className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
        {label}
      </span>
      <input type="date" value={value} onChange={e => onChange(e.target.value)}
              data-testid={testid}
              className="mt-1 px-2.5 h-9 rounded border border-border bg-bg text-fg text-sm font-mono focus:outline-none focus:border-primary"/>
    </label>
  );
}

// ─────────────────────────────────────────── Phase 15.2 · C — Stuck movements
function StuckPanel() {
  const [threshold, setThreshold] = useState(24);
  const { data, isLoading, mutate } = useStuckMovements(threshold);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [confirmTarget, setConfirmTarget] = useState<StuckMovement | null>(null);

  if (!isLoading && (data || []).length === 0) return null;

  return (
    <section className="prosper-card p-4 border-warning/40"
             data-testid="ramp-stuck-panel">
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="flex items-center gap-2">
          <AlertTriangle size={14} className="text-warning"/>
          <h3 className="font-display font-bold text-fg text-sm">
            Movimientos atascados ({data?.length || 0})
          </h3>
        </div>
        <div className="flex items-center gap-2 text-[11px]">
          <span className="text-fg-subtle font-mono uppercase tracking-wider">Umbral</span>
          <select value={threshold} onChange={e => setThreshold(+e.target.value)}
                  data-testid="ramp-stuck-threshold"
                  className="px-2 h-7 rounded border border-border bg-bg text-fg text-xs font-mono">
            <option value={1}>1h</option>
            <option value={6}>6h</option>
            <option value={24}>24h</option>
            <option value={72}>72h</option>
          </select>
          <button onClick={() => mutate()}
                  className="prosper-btn-ghost h-7 text-[11px] gap-1.5">
            <RefreshCw size={10}/> Refrescar
          </button>
        </div>
      </div>
      <p className="text-[11px] text-fg-muted mb-3 max-w-2xl">
        Pending/TransferPending/Processing más viejos que el umbral. No se
        transicionan automáticamente. Re-sincronizá contra Andes para confirmar
        que de verdad no avanzó, y solo entonces marcalo como Failed (libera
        caps).
      </p>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle border-b border-border">
            <th className="text-left  py-1.5">Movimiento</th>
            <th className="text-left  py-1.5">Cliente</th>
            <th className="text-right py-1.5">Monto</th>
            <th className="text-right py-1.5">Antigüedad</th>
            <th className="text-right py-1.5 pr-2">Acciones</th>
          </tr>
        </thead>
        <tbody>
          {(data || []).map(m => (
            <tr key={m.id} className="border-b border-border/40"
                data-testid={`ramp-stuck-row-${m.id}`}>
              <td className="py-1.5">
                <div className="font-mono text-[10px]">{m.id}</div>
                <div className="text-fg font-display font-semibold capitalize">
                  {m.kind} {m.country ? `· ${m.country.toUpperCase()}` : ""}
                </div>
                <div className="text-[10px] font-mono text-fg-subtle">
                  {m.asset} · {m.chain}
                </div>
              </td>
              <td className="py-1.5 text-fg-muted">{m.end_customer_id}</td>
              <td className="py-1.5 text-right font-mono tabular text-fg">
                {fmtArsaAdmin(m.amount || "0")}
              </td>
              <td className="py-1.5 text-right font-mono text-warning">
                {m.age_hours}h
              </td>
              <td className="py-1.5 pr-2 text-right">
                <button
                  data-testid={`ramp-stuck-resync-${m.id}`}
                  disabled={busyId === m.id}
                  onClick={async () => {
                    setBusyId(m.id);
                    try {
                      const r = await resyncMovement(m.id);
                      toast(r?.gateway_status
                        ? `Andes dice: ${r.gateway_status}`
                        : "Sin coincidencia en Andes");
                    } catch (e: any) {
                      toast.error(e?.message || "resync failed");
                    } finally { setBusyId(null); }
                  }}
                  className="prosper-btn-ghost h-7 text-[10px] gap-1 mr-1">
                  <Wrench size={9}/> Re-sync
                </button>
                <button
                  data-testid={`ramp-stuck-fail-${m.id}`}
                  onClick={() => setConfirmTarget(m)}
                  className="prosper-btn-ghost h-7 text-[10px] gap-1 text-danger hover:bg-danger/10">
                  <XCircle size={9}/> Marcar fallido
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {confirmTarget && (
        <MarkFailedModal
          mv={confirmTarget}
          onClose={() => setConfirmTarget(null)}
          onSuccess={() => { setConfirmTarget(null); mutate(); }}/>
      )}
    </section>
  );
}

function MarkFailedModal({ mv, onClose, onSuccess }: {
  mv: StuckMovement; onClose: () => void; onSuccess: () => void;
}) {
  const [reason, setReason] = useState("");
  const [refund, setRefund] = useState(true);
  const [busy, setBusy] = useState(false);
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-bg/80 backdrop-blur-sm"
         data-testid="ramp-mark-failed-modal">
      <div className="prosper-card p-5 max-w-md w-full mx-4 space-y-3">
        <div className="flex items-center gap-2">
          <XCircle size={16} className="text-danger"/>
          <h3 className="font-display font-bold text-fg text-base">
            Marcar movimiento como fallido
          </h3>
        </div>
        <div className="text-[11px] text-fg-muted">
          {mv.kind} · {mv.id} · {fmtArsaAdmin(mv.amount || "0")} {mv.asset}
        </div>
        <div>
          <label className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
            Motivo (obligatorio)
          </label>
          <textarea
            data-testid="ramp-mark-failed-reason"
            value={reason} onChange={e => setReason(e.target.value)}
            rows={3}
            placeholder="Ej: Andes confirma vía soporte que la TX no llegó al destino"
            className="prosper-input mt-1 w-full text-xs"/>
        </div>
        <label className="flex items-center gap-2 text-xs">
          <input type="checkbox" checked={refund}
                 data-testid="ramp-mark-failed-refund"
                 onChange={e => setRefund(e.target.checked)}/>
          Devolver el saldo congelado de ARSa al cliente
        </label>
        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose}
                  className="prosper-btn-ghost h-9 text-xs">Cancelar</button>
          <button
            data-testid="ramp-mark-failed-submit"
            disabled={busy || reason.trim().length < 3}
            onClick={async () => {
              setBusy(true);
              try {
                await markMovementFailed(mv.id, reason.trim(), refund);
                toast.success("Marcado como Failed · caps liberados");
                onSuccess();
              } catch (e: any) {
                toast.error(e?.message || "No se pudo marcar");
              } finally { setBusy(false); }
            }}
            className="prosper-btn-primary h-9 text-xs gap-1.5 bg-danger text-white hover:bg-danger/80">
            <XCircle size={11}/> Confirmar Failed
          </button>
        </div>
      </div>
    </div>
  );
}
