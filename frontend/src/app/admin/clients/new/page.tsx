"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { PageHeader } from "@prosper/ui";
import { toast } from "sonner";
import { Save, X } from "lucide-react";
import { createClient } from "@/lib/admin-clients";
import { cn } from "@/lib/utils";

export default function NewClientPage() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [domains, setDomains] = useState<string[]>([]);
  const [domainDraft, setDomainDraft] = useState("");
  const [form, setForm] = useState({
    legal_name: "", commercial_name: "", country: "AR",
    tax_id: "", type: "fintech", expected_aum_usd: 0,
    start_date: "",
    primary_email: "", primary_name: "", primary_phone: "",
    tier: "T2",
    caps: {
      subscribe_daily_cap_usd:   100_000,
      subscribe_monthly_cap_usd: 2_000_000,
      redeem_daily_cap_usd:      100_000,
      redeem_monthly_cap_usd:    2_000_000,
    },
    notes: "", env: "sandbox",
  });

  const valid = form.legal_name.length >= 2
    && form.tax_id.length >= 4
    && /\S+@\S+\.\S+/.test(form.primary_email)
    && form.primary_name.length >= 2;

  const submit = async () => {
    if (!valid) return;
    setBusy(true);
    try {
      const res = await createClient({ ...form, domain_allowlist: domains });
      toast.success(`Cliente creado · email enviado a ${form.primary_email}`);
      router.push(`/admin/clients/${res.org.org_id}`);
    } catch (e: any) { toast.error(e?.message || "Error al crear cliente"); setBusy(false); }
  };

  const addDomain = () => {
    const d = domainDraft.trim().toLowerCase().replace(/^@/, "");
    if (d && !domains.includes(d)) setDomains([...domains, d]);
    setDomainDraft("");
  };

  return (
    <div data-testid="admin-clients-new-page">
      <PageHeader
        breadcrumbs={[{ label: "Admin", href: "/admin" },
                      { label: "Clientes", href: "/admin/clients" },
                      { label: "Nuevo" }]}
        kicker="Phase 6"
        title="Nuevo cliente"
        subtitle="Da de alta una organización en Prosper. Se crea el primer usuario admin y se envía email de invitación."
      />

      <div className="max-w-3xl space-y-5">
        <Section title="1 · Información corporativa">
          <Grid>
            <Field label="Razón social" required>
              <input value={form.legal_name} onChange={(e) => setForm({ ...form, legal_name: e.target.value })}
                data-testid="new-legal-name" className={inputCls} placeholder="Acme Holdings SA" />
            </Field>
            <Field label="Nombre comercial">
              <input value={form.commercial_name} onChange={(e) => setForm({ ...form, commercial_name: e.target.value })}
                data-testid="new-commercial-name" className={inputCls} placeholder="Acme" />
            </Field>
            <Field label="País" required>
              <select value={form.country} onChange={(e) => setForm({ ...form, country: e.target.value })}
                data-testid="new-country" className={inputCls}>
                {["AR","UY","CL","BR","MX","CO","PE","ES","US","GB","UK","CH"].map((c) =>
                  <option key={c} value={c}>{c}</option>)}
              </select>
            </Field>
            <Field label="Tax ID / CUIT" required>
              <input value={form.tax_id} onChange={(e) => setForm({ ...form, tax_id: e.target.value })}
                data-testid="new-tax-id" className={inputCls} placeholder="30-71234567-8" />
            </Field>
            <Field label="Tipo de cliente">
              <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}
                data-testid="new-type" className={inputCls}>
                {["fintech","broker","family_office","retail_aggregator","other"].map((t) =>
                  <option key={t} value={t}>{t}</option>)}
              </select>
            </Field>
            <Field label="AUM esperado (USD)">
              <input type="number" value={form.expected_aum_usd}
                onChange={(e) => setForm({ ...form, expected_aum_usd: Number(e.target.value) })}
                data-testid="new-aum" className={inputCls} placeholder="500000" />
            </Field>
            <Field label="Fecha estimada de inicio">
              <input type="date" value={form.start_date}
                onChange={(e) => setForm({ ...form, start_date: e.target.value })}
                data-testid="new-start-date" className={inputCls} />
            </Field>
            <Field label="Ambiente">
              <select value={form.env} onChange={(e) => setForm({ ...form, env: e.target.value })}
                data-testid="new-env" className={inputCls}>
                <option value="sandbox">sandbox</option>
                <option value="production">production</option>
              </select>
            </Field>
          </Grid>
        </Section>

        <Section title="2 · Contacto y acceso">
          <Grid>
            <Field label="Email del contacto primario" required>
              <input type="email" value={form.primary_email}
                onChange={(e) => setForm({ ...form, primary_email: e.target.value })}
                data-testid="new-primary-email" className={inputCls} placeholder="founder@cliente.com" />
            </Field>
            <Field label="Nombre completo" required>
              <input value={form.primary_name}
                onChange={(e) => setForm({ ...form, primary_name: e.target.value })}
                data-testid="new-primary-name" className={inputCls} placeholder="Juan Pérez" />
            </Field>
            <Field label="Teléfono">
              <input value={form.primary_phone}
                onChange={(e) => setForm({ ...form, primary_phone: e.target.value })}
                data-testid="new-primary-phone" className={inputCls} placeholder="+54 11 …" />
            </Field>
          </Grid>
          <div className="mt-3">
            <label className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
              Domain allowlist
            </label>
            <p className="text-[10px] text-fg-subtle mt-0.5 mb-1.5">
              Usuarios que se registren con estos dominios se mapean automáticamente a esta organización.
            </p>
            <div className="flex gap-2">
              <input value={domainDraft} onChange={(e) => setDomainDraft(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addDomain())}
                data-testid="new-domain-input"
                placeholder="@cliente.com"
                className={cn(inputCls, "flex-1")} />
              <button type="button" onClick={addDomain}
                data-testid="new-domain-add"
                className="prosper-btn-ghost h-9 px-3 text-xs">Add</button>
            </div>
            <div className="flex flex-wrap gap-1.5 mt-2">
              {domains.map((d) => (
                <span key={d} data-testid={`domain-chip-${d}`}
                      className="inline-flex items-center gap-1 px-2 py-1 rounded
                                bg-primary/10 text-primary border border-primary/30
                                font-mono text-[10px]">
                  @{d}
                  <button onClick={() => setDomains(domains.filter((x) => x !== d))}
                          className="hover:text-danger"><X size={9}/></button>
                </span>
              ))}
            </div>
          </div>
        </Section>

        <Section title="3 · Configuración interna">
          <Grid>
            <Field label="Tier de comisiones">
              <select value={form.tier} onChange={(e) => setForm({ ...form, tier: e.target.value })}
                data-testid="new-tier" className={inputCls}>
                <option value="T1">T1 · Top tier</option>
                <option value="T2">T2 · Standard</option>
                <option value="T3">T3 · Mass</option>
              </select>
            </Field>
            {(["subscribe_daily_cap_usd","subscribe_monthly_cap_usd",
                "redeem_daily_cap_usd","redeem_monthly_cap_usd"] as const).map((k) => (
              <Field key={k} label={k.replace(/_/g, " ").replace("usd","USD")}>
                <input type="number" value={(form.caps as any)[k]}
                  onChange={(e) => setForm({ ...form, caps: { ...form.caps, [k]: Number(e.target.value) } })}
                  data-testid={`new-cap-${k}`} className={inputCls} />
              </Field>
            ))}
          </Grid>
          <div className="mt-3">
            <label className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
              Notas internas (solo backoffice)
            </label>
            <textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })}
              rows={3} data-testid="new-notes"
              placeholder="Notas internas, contexto comercial, etc."
              className={cn(inputCls, "mt-1.5 font-sans")} />
          </div>
        </Section>

        <div className="flex items-center justify-between sticky bottom-0 bg-bg pt-4 pb-2 border-t border-border">
          <a href="/admin/clients" className="text-xs text-fg-subtle hover:text-fg">← Cancelar</a>
          <button onClick={submit} disabled={!valid || busy}
            data-testid="new-submit"
            className="prosper-btn-primary h-10 px-5 text-xs gap-1.5 disabled:opacity-40">
            <Save size={13}/> {busy ? "Creando…" : "Crear cliente · enviar invitación"}
          </button>
        </div>
      </div>
    </div>
  );
}

const inputCls = "w-full h-9 px-3 rounded border border-border bg-surface text-xs " +
                  "focus:outline-none focus:border-primary font-mono";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="prosper-card p-5">
      <h2 className="text-[10px] font-mono uppercase tracking-[0.2em] text-fg-subtle mb-4">{title}</h2>
      {children}
    </section>
  );
}
function Grid({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-1 md:grid-cols-2 gap-3">{children}</div>;
}
function Field({ label, required, children }:
  { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div>
      <label className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
        {label}{required && <span className="text-danger ml-1">*</span>}
      </label>
      <div className="mt-1">{children}</div>
    </div>
  );
}
