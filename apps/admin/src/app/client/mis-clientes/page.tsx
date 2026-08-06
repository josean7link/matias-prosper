"use client";
import { useState } from "react";
import useSWR from "swr";
import { Badge, PageHeader } from "@prosper/ui";
import { Users, Plus, Mail, Save, X, AlertTriangle } from "lucide-react";
import { toast } from "sonner";

const f = (u: string) => fetch(u, { credentials: "include" }).then(r => r.json());
const api = (u: string, init?: RequestInit) =>
  fetch(u, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  }).then(async r => {
    const j = await r.json();
    if (!r.ok) throw new Error(j?.detail || `${r.status}`);
    return j;
  });

interface Subclient {
  org_id: string;
  commercial_name: string;
  legal_name: string;
  country: string;
  kyb_status: string;
  arsa_balance: number;
  position_count: number;
  total_aum_usd: number;
  last_activity_at: string | null;
  contact_email: string | null;
  created_at: string;
}

interface MeOut {
  user: { user_id: string; email: string; org_id: string };
  org:  { org_id: string; commercial_name?: string;
            parent_org_id?: string | null; level?: number } | null;
  role: string;
}

/** Phase 23 — N1 portal: "Mis clientes" (read-only summary + Create N2). */
export default function MyClientsPage() {
  const me = useSWR<MeOut>("/api/v1/me", f);
  const orgId = me.data?.user?.org_id;
  const isN1 = (me.data?.org?.parent_org_id ?? null) == null;

  const { data, mutate, isLoading } = useSWR<Subclient[]>(
    orgId && isN1 ? `/api/v1/clients/${orgId}/subclients` : null, f);

  const [creating, setCreating] = useState(false);

  if (me.isLoading) return null;

  if (!isN1) {
    return (
      <div className="space-y-6">
        <PageHeader
          crumbs={[{ label: "Cliente" }, { label: "Mis clientes" }]}
          title="Mis clientes"/>
        <section className="prosper-card p-6 text-center" data-testid="mis-clientes-n2-locked">
          <AlertTriangle size={20} className="text-warning mx-auto mb-2"/>
          <p className="font-display text-base text-fg">
            Tu cuenta no puede crear sub-clientes
          </p>
          <p className="text-xs text-fg-muted mt-1">
            Sos un cliente N2 — solo el cliente N1 que te invitó tiene esta función.
          </p>
        </section>
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="mis-clientes-page">
      <PageHeader
        crumbs={[{ label: "Cliente" }, { label: "Mis clientes" }]}
        title="Mis clientes"
        subtitle="Vista de solo lectura · cada cliente opera con su propia cuenta Andes y posiciones."
        actions={
          <button onClick={() => setCreating(true)}
                  data-testid="mis-clientes-create-btn"
                  className="prosper-btn-primary h-9 text-xs gap-1.5">
            <Plus size={11}/> Crear cliente
          </button>
        }/>

      <section className="prosper-card p-5">
        <table className="w-full text-xs" data-testid="mis-clientes-table">
          <thead>
            <tr className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle border-b border-border">
              <th className="text-left  py-2">Cliente</th>
              <th className="text-left  py-2">Contacto</th>
              <th className="text-left  py-2">KYB</th>
              <th className="text-right py-2">Saldo ARSa</th>
              <th className="text-right py-2">Posiciones</th>
              <th className="text-right py-2">AUM (USD)</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr><td colSpan={6} className="py-4 text-center text-fg-subtle italic">
                Cargando…
              </td></tr>
            )}
            {(data || []).map(c => (
              <tr key={c.org_id} className="border-b border-border/40"
                  data-testid={`mis-clientes-row-${c.org_id}`}>
                <td className="py-2">
                  <div className="font-display font-bold text-fg">{c.commercial_name}</div>
                  <div className="text-[10px] font-mono text-fg-subtle">{c.legal_name} · {c.country}</div>
                </td>
                <td className="py-2 font-mono text-fg-muted text-[11px]">
                  <Mail size={9} className="inline mr-1"/>{c.contact_email || "—"}
                </td>
                <td className="py-2">
                  <Badge tone={c.kyb_status === "approved" ? "success" :
                               c.kyb_status === "rejected" ? "danger" : "warning"}
                         size="sm">
                    {c.kyb_status}
                  </Badge>
                </td>
                <td className="py-2 text-right font-mono tabular">
                  $ {c.arsa_balance.toLocaleString("es-AR", { maximumFractionDigits: 2 })}
                </td>
                <td className="py-2 text-right font-mono">{c.position_count}</td>
                <td className="py-2 text-right font-mono tabular">
                  US$ {c.total_aum_usd.toLocaleString("en-US", { maximumFractionDigits: 2 })}
                </td>
              </tr>
            ))}
            {!isLoading && (data || []).length === 0 && (
              <tr><td colSpan={6} className="py-6 text-center text-fg-subtle italic">
                Todavía no creaste ningún cliente. Hacé click en "Crear cliente" para empezar.
              </td></tr>
            )}
          </tbody>
        </table>
        <p className="mt-3 text-[10px] text-fg-subtle">
          Las cuentas de tus sub-clientes son <strong>independientes</strong>:
          cada una tiene su propia cuenta Andes (CVU + wallet ARSa), KYB,
          posiciones y caps. Vos podés ver los saldos pero no operar en su
          nombre.
        </p>
      </section>

      {creating && (
        <CreateSubclientModal
          n1OrgId={orgId!}
          onClose={() => setCreating(false)}
          onSuccess={(n2) => { setCreating(false); mutate(); toast.success(`Cliente ${n2.commercial_name} creado · invitación enviada`); }}/>
      )}
    </div>
  );
}

function CreateSubclientModal({ n1OrgId, onClose, onSuccess }: {
  n1OrgId: string; onClose: () => void; onSuccess: (n2: any) => void;
}) {
  const [legalName, setLegal] = useState("");
  const [commName, setComm]   = useState("");
  const [country, setCountry] = useState("AR");
  const [email, setEmail]     = useState("");
  const [name, setName]       = useState("");
  const [busy, setBusy]       = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      const n2 = await api(`/api/v1/clients/${n1OrgId}/subclients`, {
        method: "POST",
        body: JSON.stringify({
          legal_name: legalName,
          commercial_name: commName,
          country, contact_email: email,
          contact_full_name: name,
        }),
      });
      onSuccess(n2);
    } catch (e: any) {
      toast.error(e?.message || "No se pudo crear");
    } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-bg/80 backdrop-blur-sm"
         data-testid="mis-clientes-create-modal">
      <div className="prosper-card p-5 max-w-md w-full mx-4 space-y-3">
        <h3 className="font-display font-bold text-fg text-base flex items-center gap-2">
          <Users size={14} className="text-primary"/> Crear cliente (N2)
        </h3>
        <Field label="Razón social">
          <input className="prosper-input mt-1 w-full text-xs"
                  data-testid="mis-clientes-form-legal"
                  value={legalName} onChange={e => setLegal(e.target.value)}/>
        </Field>
        <Field label="Nombre comercial">
          <input className="prosper-input mt-1 w-full text-xs"
                  data-testid="mis-clientes-form-comm"
                  value={commName} onChange={e => setComm(e.target.value)}/>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="País (ISO)">
            <input className="prosper-input mt-1 w-full text-xs"
                    value={country} onChange={e => setCountry(e.target.value.toUpperCase())}
                    maxLength={2}/>
          </Field>
          <Field label="Email del contacto N2">
            <input type="email" className="prosper-input mt-1 w-full text-xs"
                    data-testid="mis-clientes-form-email"
                    placeholder="su.email@empresa.com"
                    value={email} onChange={e => setEmail(e.target.value)}/>
          </Field>
        </div>
        <Field label="Nombre del contacto">
          <input className="prosper-input mt-1 w-full text-xs"
                  value={name} onChange={e => setName(e.target.value)}/>
        </Field>
        <p className="text-[10px] text-fg-subtle leading-snug">
          Recibirá una invitación por email con un link de un solo uso.
          Va a tener que completar su propio KYB antes de poder operar.
        </p>
        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="prosper-btn-ghost h-9 text-xs gap-1">
            <X size={11}/> Cancelar
          </button>
          <button onClick={submit} disabled={busy || !legalName || !commName || !email}
                  data-testid="mis-clientes-form-submit"
                  className="prosper-btn-primary h-9 text-xs gap-1.5">
            <Save size={11}/> Crear y enviar invitación
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
        {label}
      </label>
      {children}
    </div>
  );
}
