"use client";
import { useState, useEffect } from "react";
import { toast } from "sonner";
import { Save, X } from "lucide-react";
import { patchClient } from "@/lib/admin-clients";
import { cn } from "@/lib/utils";

export default function InfoTab({ orgId, org, onSaved }:
  { orgId: string; org: any; onSaved: () => void }) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState(org || {});
  const [domains, setDomains] = useState<string[]>(org?.domain_allowlist || []);
  const [draft, setDraft] = useState("");
  useEffect(() => { if (org) { setForm(org); setDomains(org.domain_allowlist || []); } }, [org]);
  if (!org) return <div className="text-fg-subtle">Loading…</div>;
  const onSave = async () => {
    try {
      await patchClient(orgId, {
        commercial_name: form.commercial_name, country: form.country, type: form.type,
        expected_aum_usd: form.expected_aum_usd, primary_name: form.primary_name,
        primary_phone: form.primary_phone, tier: form.tier, notes: form.notes,
        domain_allowlist: domains,
      });
      toast.success("Guardado"); setEditing(false); onSaved();
    } catch (e: any) { toast.error(e?.message || "Failed"); }
  };
  return (
    <div className="space-y-5" data-testid="tab-content-info">
      <div className="flex justify-end">
        {editing ? (
          <div className="flex gap-2">
            <button onClick={() => { setEditing(false); setForm(org); setDomains(org.domain_allowlist || []); }}
              className="prosper-btn-ghost h-9 text-xs">Cancel</button>
            <button onClick={onSave} className="prosper-btn-primary h-9 text-xs gap-1.5"
              data-testid="info-save">
              <Save size={12}/> Guardar
            </button>
          </div>
        ) : (
          <button onClick={() => setEditing(true)} data-testid="info-edit"
            className="prosper-btn-ghost h-9 text-xs">Editar</button>
        )}
      </div>
      <div className="grid grid-cols-2 gap-x-6 gap-y-3 prosper-card p-5">
        <Row label="Razón social" value={org.legal_name} disabled />
        <Row label="Nombre comercial" value={form.commercial_name} editing={editing}
          onChange={(v) => setForm({...form, commercial_name: v})} />
        <Row label="País" value={form.country} editing={editing}
          onChange={(v) => setForm({...form, country: v})} />
        <Row label="Tax ID" value={org.tax_id} disabled />
        <Row label="Tipo" value={form.type} editing={editing}
          onChange={(v) => setForm({...form, type: v})} />
        <Row label="Tier" value={form.tier} editing={editing}
          onChange={(v) => setForm({...form, tier: v})} />
        <Row label="AUM esperado USD" value={String(form.expected_aum_usd ?? 0)} editing={editing}
          onChange={(v) => setForm({...form, expected_aum_usd: Number(v)})} numeric />
        <Row label="Contacto" value={form.primary_name} editing={editing}
          onChange={(v) => setForm({...form, primary_name: v})} />
        <Row label="Email" value={org.primary_email} disabled />
        <Row label="Teléfono" value={form.primary_phone || ""} editing={editing}
          onChange={(v) => setForm({...form, primary_phone: v})} />
        <Row label="Wallet Stellar" value={org.stellar_address || "Sin wallet asignado"} disabled />
        <Row label="Ambiente" value={org.env} disabled />
      </div>

      <div className="prosper-card p-5">
        <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-2">Domain allowlist</div>
        <div className="flex flex-wrap gap-1.5 mb-2">
          {domains.map((d) => (
            <span key={d} className="inline-flex items-center gap-1 px-2 py-1 rounded
                                      bg-primary/10 text-primary border border-primary/30
                                      font-mono text-[10px]">
              @{d}
              {editing && <button onClick={() => setDomains(domains.filter((x) => x !== d))}>
                <X size={9}/>
              </button>}
            </span>
          ))}
          {domains.length === 0 && <span className="text-fg-subtle text-xs italic">Sin dominios</span>}
        </div>
        {editing && (
          <div className="flex gap-2">
            <input value={draft} onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") { e.preventDefault();
                  const d = draft.trim().toLowerCase().replace(/^@/, "");
                  if (d && !domains.includes(d)) setDomains([...domains, d]);
                  setDraft("");
                } }}
              placeholder="@cliente.com" className="w-48 px-2 py-1.5 rounded border border-border bg-surface text-xs"/>
          </div>
        )}
      </div>

      <div className="prosper-card p-5">
        <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-2">Notas internas</div>
        {editing ? (
          <textarea value={form.notes || ""} onChange={(e) => setForm({...form, notes: e.target.value})}
            rows={4} className="w-full px-3 py-2 rounded border border-border bg-surface text-xs"/>
        ) : (
          <p className="text-xs whitespace-pre-wrap text-fg-muted">{org.notes || <span className="italic text-fg-subtle">Sin notas</span>}</p>
        )}
      </div>
    </div>
  );
}

function Row({ label, value, editing, onChange, disabled, numeric }: {
  label: string; value: string; editing?: boolean;
  onChange?: (v: string) => void; disabled?: boolean; numeric?: boolean;
}) {
  return (
    <div>
      <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-0.5">{label}</div>
      {editing && !disabled ? (
        <input value={value} type={numeric ? "number" : "text"}
          onChange={(e) => onChange?.(e.target.value)}
          className="w-full h-8 px-2 rounded border border-border bg-surface font-mono text-xs
                     focus:outline-none focus:border-primary"/>
      ) : (
        <div className={cn("text-xs", disabled ? "text-fg-subtle" : "text-fg",
                            numeric && "font-mono tabular")}>{value || "—"}</div>
      )}
    </div>
  );
}
