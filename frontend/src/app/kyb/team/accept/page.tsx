"use client";
/* Fase 8 — Página pública de aceptación de invitación de equipo. */
import { notFound, useSearchParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { kybEnabled } from "@/app/kyb/_components/KybShell";

async function apiPublic(path: string, init: RequestInit = {}) {
  const base = process.env.NEXT_PUBLIC_BACKEND_URL || "";
  const r = await fetch(`${base}${path}`, { ...init,
    headers: { "Content-Type": "application/json", ...(init.headers || {}) }});
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j?.detail || `HTTP ${r.status}`);
  return j;
}

export default function KybAcceptPage() {
  if (!kybEnabled()) notFound();
  const sp = useSearchParams();
  const token = sp?.get("token") || "";
  const [taxId, setTaxId] = useState("");
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<null | { role: string; intended_role: string }>(null);

  async function accept() {
    setBusy(true);
    try {
      const r = await apiPublic("/api/v1/kyb/team/accept",
        { method: "POST", body: JSON.stringify({
          token, tax_id: taxId, email, full_name: fullName }) });
      setDone({ role: r.role, intended_role: r.intended_role });
      toast.success("Invitación aceptada");
    } catch (e: any) { toast.error(e?.message); }
    finally { setBusy(false); }
  }

  if (done) return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <div className="max-w-md text-center" data-testid="kyb-accept-done">
        <h1 className="text-xl font-semibold text-fg">Listo</h1>
        <p className="mt-2 text-sm text-fg-muted">Te sumaste al equipo con
          el rol declarado <strong>{done.intended_role}</strong>. Al ingresar
          a la plataforma se te asignarán los permisos vigentes hoy para
          ese perfil.</p>
      </div>
    </div>);

  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <div className="max-w-md w-full bg-surface border border-border rounded-2xl p-6"
           data-testid="kyb-accept-form">
        <h1 className="text-lg font-semibold text-fg">Aceptar invitación</h1>
        <p className="mt-1 text-xs text-fg-muted">
          El CUIT/CUIL que ingreses debe coincidir con el de la invitación.
          Si no es tu número, no aceptes — avisale a quien te invitó.
        </p>
        <div className="mt-4 space-y-3">
          <label className="block text-xs text-fg-muted">CUIT/CUIL
            <input className="mt-1 w-full rounded border border-border bg-bg px-2 py-1.5 text-sm font-mono"
                   value={taxId} data-testid="kyb-accept-tax-id"
                   onChange={(e) => setTaxId(e.target.value.replace(/\D/g, "").slice(0, 11))} />
          </label>
          <label className="block text-xs text-fg-muted">Correo electrónico
            <input className="mt-1 w-full rounded border border-border bg-bg px-2 py-1.5 text-sm"
                   type="email" value={email} data-testid="kyb-accept-email"
                   onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label className="block text-xs text-fg-muted">Nombre completo (opcional)
            <input className="mt-1 w-full rounded border border-border bg-bg px-2 py-1.5 text-sm"
                   value={fullName} data-testid="kyb-accept-full-name"
                   onChange={(e) => setFullName(e.target.value)} />
          </label>
          <button className="w-full rounded-lg bg-primary text-white py-2.5 text-sm disabled:opacity-40"
                  disabled={busy || taxId.length !== 11 || !email || !token}
                  onClick={accept}
                  data-testid="kyb-accept-submit">Aceptar invitación</button>
          {!token && <p className="text-xs text-danger">Token faltante en el enlace.</p>}
        </div>
      </div>
    </div>
  );
}
