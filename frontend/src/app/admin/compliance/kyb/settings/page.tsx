"use client";
/* Fase 5a — Configuración de modos de verificación (solo super_admin,
   validado server-side). El modo mock NO aparece si environment=production:
   el backend además lo rechaza con 409 por construcción. */
import { notFound } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { kybEnabled } from "@/app/kyb/_components/KybShell";
import { getModes, putMode, CATEGORY_LABELS,
         type VerificationModes } from "@/lib/kyb-manual";

const CATEGORIES = ["identity", "screening", "company_registry"];

export default function KybVerificationSettingsPage() {
  if (!kybEnabled()) notFound();
  const [modes, setModes] = useState<VerificationModes | null>(null);
  const [err, setErr] = useState("");
  const [confirm, setConfirm] = useState<{ category: string; mode: string } | null>(null);

  const load = () => getModes().then(setModes)
    .catch((e) => setErr(e?.message || "No se pudo cargar"));
  useEffect(() => { load(); }, []);

  async function apply() {
    if (!confirm) return;
    try {
      await putMode(confirm.category, confirm.mode);
      toast.success("Modo actualizado");
      setConfirm(null); load();
    } catch (e: any) { toast.error(e?.message || "Error"); setConfirm(null); }
  }

  if (err) return <p className="p-8 text-sm text-danger" data-testid="kyb-settings-error">{err}</p>;
  if (!modes) return <p className="p-8 text-sm text-fg-muted">Cargando…</p>;

  const isProd = modes.environment === "production";
  const options = isProd ? ["manual", "automatic"] : ["manual", "automatic", "mock"];

  return (
    <div className="max-w-3xl" data-testid="kyb-settings-page">
      <h1 className="text-xl font-semibold text-fg mb-1">Modos de verificación KYB</h1>
      <p className="text-sm text-fg-muted mb-2">
        El modo se define por categoría. Los expedientes conservan el modo
        vigente al momento del envío (snapshot).</p>
      <p className="text-xs text-fg-muted mb-6" data-testid="kyb-settings-environment">
        Entorno: <strong className="text-fg">{modes.environment}</strong>
        {isProd && " — el modo simulado (mock) no está disponible en producción."}
      </p>
      <div className="space-y-4">
        {CATEGORIES.map((c) => (
          <div key={c} className="bg-surface border border-border rounded-xl p-5 flex items-center gap-4"
               data-testid={`kyb-mode-row-${c}`}>
            <div className="flex-1">
              <p className="text-sm font-medium text-fg">{CATEGORY_LABELS[c]}</p>
              <p className="text-xs text-fg-muted">Modo vigente:{" "}
                <span className="font-mono">{(modes as any)[c]?.mode}</span></p>
            </div>
            <select className="rounded-lg border border-border bg-bg px-3 py-2 text-sm text-fg"
                    value={(modes as any)[c]?.mode}
                    data-testid={`kyb-mode-select-${c}`}
                    onChange={(e) => setConfirm({ category: c, mode: e.target.value })}>
              {options.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          </div>))}
      </div>

      {confirm && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
             data-testid="kyb-mode-confirm-modal">
          <div className="bg-surface border border-border rounded-2xl p-6 max-w-md w-full">
            <h2 className="text-lg font-semibold text-fg mb-2">Confirmar cambio de modo</h2>
            <p className="text-sm text-fg-muted mb-6" data-testid="kyb-mode-confirm-text">
              A partir de ahora los expedientes nuevos usarán verificación{" "}
              <strong className="text-fg">{confirm.mode}</strong> para{" "}
              <strong className="text-fg">{CATEGORY_LABELS[confirm.category]}</strong>.
              Los casos en curso conservan el modo con el que fueron enviados.</p>
            <div className="flex gap-3">
              <button className="flex-1 rounded-lg border border-border py-2.5 text-sm text-fg hover:bg-bg"
                      data-testid="kyb-mode-confirm-cancel"
                      onClick={() => setConfirm(null)}>Cancelar</button>
              <button className="flex-1 rounded-lg bg-primary text-white py-2.5 text-sm hover:opacity-90"
                      data-testid="kyb-mode-confirm-apply"
                      onClick={apply}>Confirmar</button>
            </div>
          </div>
        </div>)}
    </div>
  );
}
