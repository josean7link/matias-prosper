"use client";
/* Fase 7 — Configuración de proveedores KYB (super_admin). */
import { notFound } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { kybEnabled } from "@/app/kyb/_components/KybShell";
import { api } from "@/lib/api";

const BASE = "/v1/admin/compliance/kyb/settings/providers";

export default function ProvidersPage() {
  if (!kybEnabled()) notFound();
  const [data, setData] = useState<any>(null);
  const load = useCallback(() => api<any>(BASE).then(setData)
    .catch((e) => toast.error(e?.message)), []);
  useEffect(() => { load(); }, [load]);
  if (!data) return <p className="p-6 text-sm text-fg-muted">Cargando…</p>;

  return (
    <div className="p-6" data-testid="kyb-providers-page">
      <h1 className="text-xl font-semibold text-fg">Proveedores de verificación</h1>
      <p className="mt-1 text-xs text-fg-muted">
        Modo de la plataforma: <span className="font-mono">{data.prosper_mode}</span>.
        Webhooks con firma inválida (30d):{" "}
        <span className={data.webhook_invalid_signatures_30d > 0
              ? "font-mono text-danger font-bold"
              : "font-mono text-fg-muted"}
              data-testid="kyb-provider-invalid-sig-count">
          {data.webhook_invalid_signatures_30d}</span>
        {data.webhook_invalid_signatures_30d > 0 && (
          <span className="ml-2 text-danger">
            ↑ verificá configuración o intento de falsificación
          </span>)}
      </p>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        {data.items.map((it: any) =>
          <ProviderCard key={`${it.category}/${it.provider}`} cfg={it}
                        reload={load} />)}
      </div>
    </div>
  );
}

function ProviderCard({ cfg, reload }: { cfg: any; reload: () => void }) {
  const [env, setEnv] = useState<string>(cfg.environment || "");
  const [creds, setCreds] = useState("");
  const [busy, setBusy] = useState(false);
  const [calls, setCalls] = useState<any>(null);
  const path = `${BASE}/${cfg.category}/${cfg.provider}`;
  const healthOk = !!cfg.last_health_check?.ok;
  const canEnableProd = env !== "production" || healthOk;
  const [confirmModal, setConfirmModal] = useState(false);

  async function save() {
    setBusy(true);
    try {
      const body: any = {};
      if (env) body.environment = env;
      if (creds) body.credentials = creds;
      await api(path, { method: "PUT", body: JSON.stringify(body) });
      toast.success("Configuración guardada");
      setCreds(""); await reload();
    } catch (e: any) { toast.error(e?.message); } finally { setBusy(false); }
  }
  async function healthCheck() {
    setBusy(true);
    try {
      const r = await api<any>(`${path}/health-check`, { method: "POST" });
      toast[r.ok ? "success" : "error"](
        r.ok ? `Health OK · ${r.latency_ms}ms` : `Health FAIL: ${r.error}`);
      await reload();
    } catch (e: any) { toast.error(e?.message); } finally { setBusy(false); }
  }
  async function toggle() {
    setBusy(true);
    try {
      await api(`${path}/enable`, {
        method: "POST", body: JSON.stringify({ enabled: !cfg.enabled }) });
      toast.success(cfg.enabled ? "Proveedor desactivado" : "Proveedor activado");
      setConfirmModal(false); await reload();
    } catch (e: any) { toast.error(e?.message); } finally { setBusy(false); }
  }
  async function loadCalls() {
    try { setCalls(await api<any>(`${path}/calls`)); }
    catch (e: any) { toast.error(e?.message); }
  }

  return (
    <div className="rounded-xl border border-border bg-surface p-4"
         data-testid={`kyb-provider-card-${cfg.category}-${cfg.provider}`}>
      <div className="flex items-baseline justify-between">
        <p className="text-sm font-medium text-fg">
          {cfg.category} · <span className="font-mono">{cfg.provider}</span>
        </p>
        <span className={`text-[10px] px-1.5 py-0.5 rounded ${
            cfg.enabled ? "bg-success/15 text-success"
                        : "bg-fg-muted/15 text-fg-muted"}`}>
          {cfg.enabled ? "activo" : "inactivo"}
        </span>
      </div>
      <div className="mt-3 space-y-2">
        <label className="block text-xs text-fg-muted">Entorno
          <select className="mt-1 w-full rounded border border-border bg-bg px-2 py-1 text-sm"
                  value={env} onChange={(e) => setEnv(e.target.value)}
                  data-testid={`kyb-provider-env-${cfg.category}-${cfg.provider}`}>
            <option value="">(sin definir)</option>
            <option value="sandbox">sandbox</option>
            <option value="production">production</option>
          </select>
        </label>
        <label className="block text-xs text-fg-muted">Credenciales (write-only)
          <input className="mt-1 w-full rounded border border-border bg-bg px-2 py-1 text-sm"
                 type="password" placeholder={cfg.credentials_last4
                    ? `••• guardadas (${cfg.credentials_last4})`
                    : "sin cargar"}
                 value={creds} onChange={(e) => setCreds(e.target.value)}
                 data-testid={`kyb-provider-creds-${cfg.category}-${cfg.provider}`} />
        </label>
        <p className="text-[11px] text-fg-muted font-mono"
           data-testid={`kyb-provider-health-${cfg.category}-${cfg.provider}`}>
          Último health: {cfg.last_health_check
            ? `${cfg.last_health_check.ok ? "OK" : "FAIL"} · ${cfg.last_health_check.latency_ms}ms · ${cfg.last_health_check.checked_at?.slice(0, 19)}`
            : "sin correr"}
        </p>
        <div className="flex flex-wrap gap-2 pt-1">
          <button className="rounded border border-border px-2 py-1 text-xs disabled:opacity-40"
                  disabled={busy || (!env && !creds)}
                  data-testid={`kyb-provider-save-${cfg.category}-${cfg.provider}`}
                  onClick={save}>Guardar</button>
          <button className="rounded border border-border px-2 py-1 text-xs disabled:opacity-40"
                  disabled={busy}
                  data-testid={`kyb-provider-health-btn-${cfg.category}-${cfg.provider}`}
                  onClick={healthCheck}>Probar conexión</button>
          <button className="rounded border border-primary/50 text-primary px-2 py-1 text-xs disabled:opacity-40"
                  disabled={busy || !canEnableProd}
                  title={!canEnableProd
                    ? "En producción se requiere un health check exitoso antes de activar"
                    : ""}
                  data-testid={`kyb-provider-enable-${cfg.category}-${cfg.provider}`}
                  onClick={() => cfg.enabled ? toggle() : setConfirmModal(true)}>
            {cfg.enabled ? "Desactivar" : "Activar"}
          </button>
          <button className="rounded border border-border px-2 py-1 text-xs"
                  data-testid={`kyb-provider-calls-btn-${cfg.category}-${cfg.provider}`}
                  onClick={loadCalls}>Ver últimas llamadas</button>
        </div>
      </div>
      {calls && (
        <div className="mt-3 border-t border-border pt-2 text-[11px] font-mono text-fg-muted">
          <p>Firma inválida (30d):{" "}
            <span className={calls.invalid_signatures_30d > 0 ? "text-danger" : ""}>
              {calls.invalid_signatures_30d}</span></p>
          <p className="mt-1 text-fg">Últimas salientes</p>
          {calls.outbound.slice(0, 5).map((c: any, i: number) => (
            <p key={i}>· {c.endpoint} · {c.status_code} · {c.latency_ms}ms</p>))}
          <p className="mt-1 text-fg">Últimos webhooks</p>
          {calls.webhooks.slice(0, 5).map((c: any, i: number) => (
            <p key={i}>· {c.endpoint} · sig={String(c.signature_valid)}</p>))}
          {calls.outbound.length === 0 && calls.webhooks.length === 0 &&
            <p>Sin llamadas registradas.</p>}
        </div>)}
      {confirmModal && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
          <div className="bg-surface border border-border rounded-2xl p-5 max-w-md w-full"
               data-testid={`kyb-provider-confirm-${cfg.category}-${cfg.provider}`}>
            <h2 className="text-base font-semibold text-fg mb-2">
              Activar {cfg.category}/{cfg.provider}</h2>
            <p className="text-sm text-fg-muted">
              Al confirmar: los expedientes <strong>nuevos</strong> usarán
              verificación automática para <span className="font-mono">
              {cfg.category}</span>. Los casos <strong>en curso</strong>{" "}
              conservan el modo con el que fueron enviados.
            </p>
            <div className="mt-3 flex gap-2">
              <button className="flex-1 rounded border border-border py-1.5 text-sm"
                      onClick={() => setConfirmModal(false)}>Cancelar</button>
              <button className="flex-1 rounded bg-primary text-white py-1.5 text-sm"
                      onClick={toggle}
                      data-testid={`kyb-provider-confirm-btn-${cfg.category}-${cfg.provider}`}>
                Confirmar</button>
            </div>
          </div>
        </div>)}
    </div>
  );
}
