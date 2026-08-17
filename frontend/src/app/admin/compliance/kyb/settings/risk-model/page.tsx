"use client";
/* Fase 7 — Modelo de riesgo (super_admin). Edición + preview + versionado. */
import { notFound } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { kybEnabled } from "@/app/kyb/_components/KybShell";
import { api } from "@/lib/api";

const BASE = "/v1/admin/compliance/kyb/settings/risk-model";

export default function RiskModelPage() {
  if (!kybEnabled()) notFound();
  const [model, setModel] = useState<any>(null);
  const [preview, setPreview] = useState<any>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try {
      const [m, h] = await Promise.all([
        api<any>(BASE), api<any>(`${BASE}/history`)]);
      setModel(m); setHistory(h.items || []);
    } catch (e: any) { toast.error(e?.message); }
  }, []);
  useEffect(() => { load(); }, [load]);
  if (!model) return <p className="p-6 text-sm text-fg-muted">Cargando…</p>;

  function upFactor(i: number, key: string, val: any) {
    const factors = model.factors.slice();
    factors[i] = { ...factors[i], [key]: val };
    setModel({ ...model, factors });
  }
  function upThr(k: string, val: number) {
    setModel({ ...model, thresholds: { ...model.thresholds, [k]: val } });
  }
  function upReview(k: string, val: number) {
    setModel({ ...model, review_months: { ...model.review_months, [k]: val } });
  }

  async function runPreview() {
    setBusy(true);
    try {
      const r = await api<any>(`${BASE}/preview`, {
        method: "POST", body: JSON.stringify({
          factors: model.factors, thresholds: model.thresholds,
          review_months: model.review_months })});
      setPreview(r);
    } catch (e: any) { toast.error(e?.message); } finally { setBusy(false); }
  }
  async function save() {
    setBusy(true);
    try {
      const r = await api<any>(BASE, { method: "PUT",
        body: JSON.stringify({
          factors: model.factors, thresholds: model.thresholds,
          review_months: model.review_months })});
      toast.success(`Publicada versión ${r.version}`);
      await load(); setPreview(null);
    } catch (e: any) { toast.error(e?.message); } finally { setBusy(false); }
  }

  return (
    <div className="p-6" data-testid="kyb-risk-model-page">
      <h1 className="text-xl font-semibold text-fg">
        Modelo de riesgo <span className="text-xs text-fg-muted font-mono">
        v{model.version} · {model.active ? "activa" : "inactiva"}</span>
      </h1>
      <p className="text-xs text-fg-muted mt-1">
        Cada guardado incrementa la versión; solo hay una activa. Cada caso
        recuerda con qué versión se calculó su riesgo.
      </p>

      <div className="mt-4 bg-surface border border-border rounded-xl p-4">
        <p className="text-sm font-medium text-fg">Factores</p>
        <div className="mt-2 space-y-1">
          {model.factors.map((f: any, i: number) => (
            <div key={f.key} className="flex flex-wrap items-center gap-2 text-sm"
                 data-testid={`kyb-risk-factor-${f.key}`}>
              <span className="font-mono text-xs text-fg-muted w-40">{f.key}</span>
              <input className="flex-1 min-w-[10rem] rounded border border-border bg-bg px-2 py-1 text-sm"
                     value={f.label || ""} onChange={(e) => upFactor(i, "label", e.target.value)} />
              <span className="text-xs text-fg-muted">peso</span>
              <input className="w-20 rounded border border-border bg-bg px-2 py-1 text-sm"
                     type="number" value={f.weight ?? 0}
                     onChange={(e) => upFactor(i, "weight", Number(e.target.value))}
                     data-testid={`kyb-risk-factor-weight-${f.key}`} />
              <span className="text-xs text-fg-muted">tipo</span>
              <span className="font-mono text-xs">{f.type}</span>
            </div>))}
        </div>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <div className="bg-surface border border-border rounded-xl p-4">
          <p className="text-sm font-medium text-fg">Umbrales</p>
          {["low_max", "medium_max"].map((k) => (
            <label key={k} className="mt-2 flex items-center gap-2 text-sm">
              <span className="font-mono text-xs text-fg-muted w-24">{k}</span>
              <input className="w-24 rounded border border-border bg-bg px-2 py-1 text-sm"
                     type="number" value={model.thresholds[k] ?? 0}
                     data-testid={`kyb-risk-threshold-${k}`}
                     onChange={(e) => upThr(k, Number(e.target.value))} />
            </label>))}
          <p className="mt-2 text-[11px] text-fg-muted">
            score ≤ low_max → low; ≤ medium_max → medium; sino → high.
          </p>
        </div>
        <div className="bg-surface border border-border rounded-xl p-4">
          <p className="text-sm font-medium text-fg">Revisión periódica (meses)</p>
          {["low", "medium", "high"].map((k) => (
            <label key={k} className="mt-2 flex items-center gap-2 text-sm">
              <span className="font-mono text-xs text-fg-muted w-24">{k}</span>
              <input className="w-24 rounded border border-border bg-bg px-2 py-1 text-sm"
                     type="number" value={model.review_months[k] ?? 0}
                     data-testid={`kyb-risk-review-${k}`}
                     onChange={(e) => upReview(k, Number(e.target.value))} />
            </label>))}
        </div>
      </div>

      <div className="mt-4 flex gap-2">
        <button className="rounded border border-border px-3 py-1.5 text-sm disabled:opacity-40"
                disabled={busy} onClick={runPreview}
                data-testid="kyb-risk-preview-button">
          Vista previa del impacto</button>
        <button className="rounded bg-primary text-white px-3 py-1.5 text-sm disabled:opacity-40"
                disabled={busy} onClick={save}
                data-testid="kyb-risk-save-button">
          Guardar y publicar nueva versión</button>
      </div>

      {preview && (
        <div className="mt-4 bg-surface border border-border rounded-xl p-4"
             data-testid="kyb-risk-preview-result">
          <p className="text-sm text-fg">
            Casos evaluados: <strong>{preview.cases_evaluated}</strong> ·
            Sin cambio: <strong>{preview.stayed}</strong> ·
            <span className={preview.changed.length > 0 ? "text-warning" : ""}>
              {" "}Cambian de nivel: <strong>{preview.changed.length}</strong></span>
          </p>
          <div className="mt-2 space-y-1">
            {preview.changed.map((c: any) => (
              <p key={c.case_id} className="text-xs text-fg-muted font-mono">
                {c.case_id} — {c.company_name || "—"} · {c.from || "—"} → {c.to}
                {" "}(score {c.old_score ?? "—"} → {c.new_score})
              </p>))}
          </div>
        </div>)}

      <div className="mt-6 bg-surface border border-border rounded-xl p-4">
        <p className="text-sm font-medium text-fg">Historial</p>
        <div className="mt-2 space-y-1">
          {history.map((h) => (
            <p key={h.version} className="text-xs text-fg-muted font-mono">
              v{h.version} {h.active ? "· activa" : ""} · publicada{" "}
              {h.created_at?.slice(0, 19)} por {h.updated_by || "—"}
            </p>))}
        </div>
      </div>
    </div>
  );
}
