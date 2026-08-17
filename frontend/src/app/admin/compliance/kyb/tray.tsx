"use client";
/* Fase 6 — Bandeja nueva KYB (reemplaza la legacy con el flag on). */
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

const BASE = "/v1/admin/compliance/kyb";
const SLA_DOT: Record<string, string> = { green: "bg-success",
  amber: "bg-warning", red: "bg-danger" };
const STATUSES = ["", "submitted", "screening", "under_review",
  "info_required", "approved", "rejected", "expired"];

export function KybTray() {
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState("");
  const [f, setF] = useState({ status: "", q: "", mine: false,
    reopened_by_alert: false, manual_pending: false, legacy: false,
    include_closed: false, include_drafts: false,
    risk_level: "", page: 1 });

  const load = useCallback(() => {
    const p = new URLSearchParams();
    Object.entries(f).forEach(([k, v]) => {
      if (v !== "" && v !== false) p.set(k, String(v)); });
    api<any>(`${BASE}/cases?${p}`).then(setData)
      .catch((e) => setErr(e?.message || "Error"));
  }, [f]);
  useEffect(() => { load(); }, [load]);

  if (err) return <p className="p-6 text-sm text-danger" data-testid="kyb-tray-error">{err}</p>;
  const chip = (key: "mine" | "reopened_by_alert" | "manual_pending" | "legacy" | "include_closed" | "include_drafts",
                label: string, cls = "") => (
    <button key={key}
            className={`rounded-full border px-3 py-1 text-xs transition-colors ${
              (f as any)[key] ? "border-primary bg-primary/10 text-primary"
                              : "border-border text-fg-muted hover:bg-bg"} ${cls}`}
            data-testid={`kyb-tray-chip-${key}`}
            onClick={() => setF({ ...f, [key]: !(f as any)[key], page: 1 })}>
      {label}</button>);

  return (
    <div data-testid="kyb-tray">
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <input className="rounded-lg border border-border bg-bg px-3 py-1.5 text-sm text-fg w-64"
               placeholder="Razón social o CUIT…" value={f.q}
               data-testid="kyb-tray-search"
               onChange={(e) => setF({ ...f, q: e.target.value, page: 1 })} />
        <select className="rounded-lg border border-border bg-bg px-2 py-1.5 text-sm text-fg"
                value={f.status} data-testid="kyb-tray-status-filter"
                onChange={(e) => setF({ ...f, status: e.target.value, page: 1 })}>
          {STATUSES.map((s) => <option key={s} value={s}>{s || "Todos los estados"}</option>)}
        </select>
        <select className="rounded-lg border border-border bg-bg px-2 py-1.5 text-sm text-fg"
                value={f.risk_level} data-testid="kyb-tray-risk-filter"
                onChange={(e) => setF({ ...f, risk_level: e.target.value, page: 1 })}>
          <option value="">Riesgo: todos</option>
          {["low", "medium", "high"].map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        {chip("mine", "Mis casos")}
        {chip("reopened_by_alert", "⚠ Reabiertos por alerta")}
        {chip("manual_pending", "Verificación manual pendiente")}
        {chip("legacy", "Migrados del legacy")}
        {chip("include_drafts", "Incluir borradores")}
        {chip("include_closed", "Incluir cerrados")}
      </div>
      {data?.workload?.length > 0 && (
        <p className="text-xs text-fg-muted mb-2" data-testid="kyb-tray-workload">
          Carga (checklists pendientes): {data.workload.map((w: any) =>
            `${w.assigned_to || "sin asignar"}: ${w.pending}`).join(" · ")}
        </p>)}
      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full text-sm">
          <thead className="bg-bg text-left text-xs text-fg-muted">
            <tr>{["Organización", "CUIT", "País", "Estado", "Riesgo",
                  "Analista", "Antigüedad/SLA", "Hits", "Checks pend.",
                  "Verificación", ""].map((h) => (
              <th key={h} className="px-3 py-2.5 font-medium">{h}</th>))}</tr>
          </thead>
          <tbody className="divide-y divide-border bg-surface">
            {(data?.items || []).map((c: any) => (
              <tr key={c.case_id} data-testid={`kyb-tray-row-${c.case_id}`}
                  className="hover:bg-bg/60">
                <td className="px-3 py-2.5">
                  <span className="text-fg">{c.company_name}</span>
                  <span className="block text-[10px] text-fg-muted font-mono">
                    {c.case_id}
                    {c.legacy_origin && <span className="ml-1 rounded bg-warning/15 text-warning px-1" data-testid={`kyb-badge-legacy-${c.case_id}`}>legacy</span>}
                    {c.reopen_reason === "provider_alert" && <span className="ml-1 rounded bg-danger/15 text-danger px-1" data-testid={`kyb-badge-alert-${c.case_id}`}>alerta</span>}
                    {c.priority && <span className="ml-1 rounded bg-primary/15 text-primary px-1">prioridad</span>}
                  </span></td>
                <td className="px-3 py-2.5 font-mono text-xs">{c.tax_id || "—"}</td>
                <td className="px-3 py-2.5">{c.country || "—"}</td>
                <td className="px-3 py-2.5 font-mono text-xs">{c.status}
                  {c.suspended && <span className="ml-1 text-danger">⏸</span>}</td>
                <td className="px-3 py-2.5">{c.risk_level || "—"}</td>
                <td className="px-3 py-2.5 font-mono text-xs">{c.assigned_to || "—"}</td>
                <td className="px-3 py-2.5">
                  {c.sla && <span className={`inline-block h-2 w-2 rounded-full mr-1.5 ${SLA_DOT[c.sla]}`}
                                  data-testid={`kyb-sla-${c.case_id}`} />}
                  <span className="text-xs">{c.submitted_at?.slice(0, 10) || "—"}</span></td>
                <td className="px-3 py-2.5">{c.blocking_hits > 0 &&
                  <span className="text-danger font-medium" data-testid={`kyb-hits-${c.case_id}`}>{c.blocking_hits}</span>}</td>
                <td className="px-3 py-2.5">{c.pending_checks > 0 &&
                  <span className="text-warning" data-testid={`kyb-pending-${c.case_id}`}>{c.pending_checks}</span>}</td>
                <td className="px-3 py-2.5 text-[10px] font-mono text-fg-muted">
                  {Object.entries(c.verification_modes || {}).map(([k, v]: any) => {
                    const st = c.verification_states?.[k];
                    const fallen = st?.startsWith("automatic_") || st === "manual_forced";
                    return <span key={k} className={fallen ? "text-warning" : ""}>
                      {k[0].toUpperCase()}:{fallen ? "↓manual" : v} </span>; })}
                </td>
                <td className="px-3 py-2.5">
                  <Link href={`/admin/compliance/kyb/${c.case_id}`}
                        className="text-primary hover:underline text-xs"
                        data-testid={`kyb-open-${c.case_id}`}>Abrir</Link></td>
              </tr>))}
            {data && data.items.length === 0 && (
              <tr><td colSpan={11} className="px-3 py-8 text-center text-sm text-fg-muted"
                      data-testid="kyb-tray-empty">Sin casos para estos filtros.</td></tr>)}
          </tbody>
        </table>
      </div>
      {data && data.total > data.page_size && (
        <div className="flex items-center gap-3 mt-3 text-xs text-fg-muted">
          <button disabled={f.page <= 1} className="disabled:opacity-40 text-primary"
                  onClick={() => setF({ ...f, page: f.page - 1 })}>← Anterior</button>
          <span>Página {data.page} · {data.total} casos · SLA {data.sla_hours}h</span>
          <button disabled={data.page * data.page_size >= data.total}
                  className="disabled:opacity-40 text-primary"
                  onClick={() => setF({ ...f, page: f.page + 1 })}>Siguiente →</button>
        </div>)}
    </div>
  );
}
