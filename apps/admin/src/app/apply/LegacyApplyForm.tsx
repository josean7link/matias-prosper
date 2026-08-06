"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import {
  ArrowRight, Building2, ChevronLeft, ShieldCheck, User as UserIcon,
} from "lucide-react";
import { ProsperLogo } from "@/components/ProsperLogo";
import { api } from "@/lib/api";

type ApplicantType = "individual" | "business";

interface UBO { full_name: string; ownership_pct: number; role?: string }

interface IndividualForm {
  contact_name: string;     // primer nombre
  last_name: string;        // apellido
  contact_email: string;
  cuit: string;             // 11 dígitos sin guiones
  birthdate: string;        // YYYY-MM-DD
  phone: string;            // E.164 +54911...
  country: string;          // AR
  jurisdiction: string;     // AR (mismo)
  use_case: string;
}

interface BusinessForm {
  legal_name: string; commercial_name: string;
  country: string; jurisdiction: string;
  incorporation_date: string; registration_number: string;
  contact_name: string; contact_email: string; contact_phone: string;
  website: string;
  expected_monthly_volume_usd: string;
  use_case: string;
  ubos: UBO[];
}

const indivInitial: IndividualForm = {
  contact_name: "", last_name: "", contact_email: "",
  cuit: "", birthdate: "", phone: "+54",
  country: "AR", jurisdiction: "AR", use_case: "",
};

const bizInitial: BusinessForm = {
  legal_name: "", commercial_name: "",
  country: "", jurisdiction: "",
  incorporation_date: "", registration_number: "",
  contact_name: "", contact_email: "", contact_phone: "",
  website: "", expected_monthly_volume_usd: "",
  use_case: "",
  ubos: [{ full_name: "", ownership_pct: 0, role: "" }],
};

/**
 * Public apply form — individuo vs empresa toggle.
 * - individuo → POST /onboarding/apply applicant_type=individual
 *   → redirect to /apply/{app_id}/kyc-docs (capturás 3 fotos).
 * - empresa → POST /onboarding/apply applicant_type=business
 *   → redirect to AiPrise hosted_url o `/apply/status?app_id=…`.
 */
export function LegacyApplyForm() {
  const router = useRouter();
  const [type, setType] = useState<ApplicantType>("individual");
  const [indiv, setIndiv] = useState<IndividualForm>(indivInitial);
  const [biz, setBiz] = useState<BusinessForm>(bizInitial);
  const [submitting, setSubmitting] = useState(false);

  // --- individuo validation
  const indivValid =
    indiv.contact_name.trim() &&
    indiv.last_name.trim() &&
    /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(indiv.contact_email) &&
    /^\d{11}$/.test(indiv.cuit) &&
    /^\d{4}-\d{2}-\d{2}$/.test(indiv.birthdate) &&
    /^\+\d{8,15}$/.test(indiv.phone);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      if (type === "individual") {
        if (!indivValid) {
          toast.error("Completá todos los campos (CUIT 11 dígitos, fecha YYYY-MM-DD, teléfono +54…).");
          setSubmitting(false);
          return;
        }
        const body = {
          applicant_type: "individual" as const,
          legal_name:    `${indiv.contact_name.trim()} ${indiv.last_name.trim()}`,
          country:       indiv.country.toUpperCase(),
          jurisdiction:  indiv.jurisdiction.toUpperCase(),
          contact_name:  indiv.contact_name.trim(),
          contact_email: indiv.contact_email.trim().toLowerCase(),
          contact_phone: indiv.phone,
          last_name:     indiv.last_name.trim(),
          cuit:          indiv.cuit,
          birthdate:     indiv.birthdate,
          phone:         indiv.phone,
          chain:         "stellar",
          use_case:      indiv.use_case || "yield",
          ubos:          [],
        };
        const res = await api<{ application_id: string; mode: string }>(
          "/v1/onboarding/apply", { method: "POST", body: JSON.stringify(body) },
        );
        toast.success("Cuenta creada — ahora subimos tus fotos para verificación.");
        router.push(`/apply/${res.application_id}/kyc-docs`);
        return;
      }

      // business
      const body = {
        applicant_type: "business" as const,
        ...biz,
        expected_monthly_volume_usd: biz.expected_monthly_volume_usd
          ? Number(biz.expected_monthly_volume_usd) : null,
        ubos: biz.ubos.filter((u) => u.full_name.trim().length > 0)
                       .map((u) => ({ ...u, ownership_pct: Number(u.ownership_pct) })),
      };
      const res = await api<{ application_id: string; hosted_url: string; mode: string }>(
        "/v1/onboarding/apply", { method: "POST", body: JSON.stringify(body) },
      );
      toast.success("Application received — redirecting to identity verification");
      if (res.hosted_url.startsWith("http")) {
        window.location.href = res.hosted_url;
      } else {
        router.push(res.hosted_url);
      }
    } catch (err) {
      const e = err as Error;
      toast.error(e.message || "Submission failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-bg" data-testid="apply-page">
      <header className="border-b border-border bg-surface">
        <div className="max-w-4xl mx-auto px-6 py-4 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2">
            <ProsperLogo />
          </Link>
          <Link href="/login"
            data-testid="apply-login-link"
            className="text-xs font-mono uppercase tracking-wider text-fg-subtle hover:text-fg">
            Ya tengo cuenta · Iniciar sesión →
          </Link>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-12">
        <div className="mb-6">
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-1">
            Apertura de cuenta
          </div>
          <h1 className="font-display font-bold text-3xl text-fg tracking-tight">
            Abrí tu cuenta Prosper
          </h1>
          <p className="text-sm text-fg-muted mt-2 max-w-xl">
            Elegí si abrís a nombre tuyo (individuo) o de tu empresa. Te pedimos lo justo
            para arrancar la verificación.
          </p>
        </div>

        {/* Toggle */}
        <div
          className="inline-flex bg-surface rounded-lg border border-border p-1 mb-8"
          role="tablist"
          data-testid="applicant-type-toggle"
        >
          <button
            type="button"
            role="tab"
            aria-selected={type === "individual"}
            data-testid="applicant-type-individual"
            onClick={() => setType("individual")}
            className={`h-10 px-5 text-sm font-display font-semibold rounded-md
                        inline-flex items-center gap-2 transition-colors
                        ${type === "individual"
                          ? "bg-primary text-white shadow-card"
                          : "text-fg-muted hover:text-fg"}`}
          >
            <UserIcon size={14}/> Individuo
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={type === "business"}
            data-testid="applicant-type-business"
            onClick={() => setType("business")}
            className={`h-10 px-5 text-sm font-display font-semibold rounded-md
                        inline-flex items-center gap-2 transition-colors
                        ${type === "business"
                          ? "bg-primary text-white shadow-card"
                          : "text-fg-muted hover:text-fg"}`}
          >
            <Building2 size={14}/> Empresa
          </button>
        </div>

        <form
          onSubmit={onSubmit}
          className="space-y-8"
          data-testid={type === "individual" ? "apply-form-individual" : "apply-form-business"}
        >
          {type === "individual" ? (
            <IndividualFields data={indiv} setData={setIndiv} />
          ) : (
            <BusinessFields data={biz} setData={setBiz} />
          )}

          <div className="flex items-center justify-between border-t border-border pt-6">
            <Link href="/" className="text-xs font-mono uppercase tracking-wider
                                       text-fg-subtle hover:text-fg flex items-center gap-1">
              <ChevronLeft size={12} /> Volver al inicio
            </Link>
            <button
              type="submit"
              disabled={submitting || (type === "individual" && !indivValid)}
              className="prosper-btn-primary h-11 px-6 text-sm gap-2 disabled:opacity-40"
              data-testid="apply-submit"
            >
              {submitting ? "Enviando…" : (
                type === "individual"
                  ? <>Continuar a fotos <ArrowRight size={14} /></>
                  : <>Submit & start KYB <ArrowRight size={14} /></>
              )}
            </button>
          </div>
        </form>
      </main>
    </div>
  );
}

/* -------------------- Individual fields -------------------- */
function IndividualFields({ data, setData }:
  { data: IndividualForm; setData: (d: IndividualForm) => void }) {
  const set = (k: keyof IndividualForm, v: string) => setData({ ...data, [k]: v });
  return (
    <>
      <Section title="Tu identidad" icon={<UserIcon size={14}/>}>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Field label="Nombre *"   value={data.contact_name}
                 onChange={(v)=>set("contact_name", v)} testid="indiv-first-name" required />
          <Field label="Apellido *" value={data.last_name}
                 onChange={(v)=>set("last_name", v)} testid="indiv-last-name" required />
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Field label="Email *" type="email" value={data.contact_email}
                 onChange={(v)=>set("contact_email", v)} testid="indiv-email" required />
          <Field label="Teléfono * (formato +5491122334455)" value={data.phone}
                 onChange={(v)=>set("phone", v)} testid="indiv-phone" required
                 placeholder="+5491122334455" />
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Field label="CUIT * (11 dígitos sin guiones)" value={data.cuit}
                 onChange={(v)=>set("cuit", v.replace(/\D/g, "").slice(0, 11))}
                 testid="indiv-cuit" required
                 placeholder="20123456789" />
          <Field label="Fecha de nacimiento * (YYYY-MM-DD)" type="date"
                 value={data.birthdate}
                 onChange={(v)=>set("birthdate", v)} testid="indiv-birthdate" required />
        </div>
      </Section>

      <Section title="Para qué vas a usar Prosper">
        <Field label="Caso de uso" value={data.use_case}
               onChange={(v)=>set("use_case", v)}
               testid="indiv-use-case"
               placeholder="Yield en pesos, ahorro en dólares, etc." />
      </Section>

      <div
        className="rounded-lg border border-primary/30 bg-primary/5 p-4 text-xs text-fg-muted"
        data-testid="indiv-next-hint"
      >
        <strong className="text-fg">Próximo paso:</strong> Vas a sacarte 3 fotos desde tu navegador
        (selfie + frente y dorso del DNI) y las validamos automáticamente con Andes.
      </div>
    </>
  );
}

/* -------------------- Business fields -------------------- */
function BusinessFields({ data, setData }:
  { data: BusinessForm; setData: (d: BusinessForm) => void }) {
  const set = (k: keyof BusinessForm, v: string) => setData({ ...data, [k]: v });
  const setUbo = (i: number, k: keyof UBO, v: string | number) =>
    setData({ ...data, ubos: data.ubos.map((u, idx) => idx === i ? { ...u, [k]: v } : u) });
  const addUbo = () =>
    setData({ ...data, ubos: [...data.ubos, { full_name: "", ownership_pct: 0 }] });
  const removeUbo = (i: number) =>
    setData({ ...data, ubos: data.ubos.filter((_, idx) => idx !== i) });

  return (
    <>
      <Section title="Empresa" icon={<Building2 size={14} />}>
        <Field label="Razón social *" value={data.legal_name}
               onChange={(v)=>set("legal_name", v)} testid="legal-name" required />
        <Field label="Nombre comercial" value={data.commercial_name}
               onChange={(v)=>set("commercial_name", v)} testid="commercial-name" />
        <div className="grid grid-cols-2 gap-3">
          <Field label="País *" value={data.country} placeholder="AR"
                 onChange={(v)=>set("country", v)} testid="country" required />
          <Field label="Jurisdicción *" value={data.jurisdiction}
                 placeholder="Buenos Aires"
                 onChange={(v)=>set("jurisdiction", v)} testid="jurisdiction" required />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Fecha de constitución" type="date"
                 value={data.incorporation_date}
                 onChange={(v)=>set("incorporation_date", v)} testid="incorp-date" />
          <Field label="Número de registro" value={data.registration_number}
                 onChange={(v)=>set("registration_number", v)} testid="reg-number" />
        </div>
        <Field label="Website" type="url" value={data.website}
               placeholder="https://"
               onChange={(v)=>set("website", v)} testid="website" />
      </Section>

      <Section title="Contacto principal" icon={<ShieldCheck size={14} />}>
        <Field label="Nombre completo *" value={data.contact_name}
               onChange={(v)=>set("contact_name", v)} testid="contact-name" required />
        <div className="grid grid-cols-2 gap-3">
          <Field label="Email *" type="email" value={data.contact_email}
                 onChange={(v)=>set("contact_email", v)}
                 testid="contact-email" required />
          <Field label="Teléfono" value={data.contact_phone} placeholder="+54 11 ..."
                 onChange={(v)=>set("contact_phone", v)} testid="contact-phone" />
        </div>
      </Section>

      <Section title="Ultimate Beneficial Owners (UBOs)">
        <div className="space-y-3">
          {data.ubos.map((u, i) => (
            <div key={i} className="grid grid-cols-12 gap-2 items-end"
                 data-testid={`ubo-row-${i}`}>
              <div className="col-span-5">
                <Field label={i === 0 ? "Nombre completo" : ""} value={u.full_name}
                  onChange={(v) => setUbo(i, "full_name", v)}
                  testid={`ubo-${i}-name`} />
              </div>
              <div className="col-span-3">
                <Field label={i === 0 ? "Ownership %" : ""} type="number"
                  value={String(u.ownership_pct)}
                  onChange={(v) => setUbo(i, "ownership_pct", v)}
                  testid={`ubo-${i}-pct`} />
              </div>
              <div className="col-span-3">
                <Field label={i === 0 ? "Rol" : ""} value={u.role || ""}
                  onChange={(v) => setUbo(i, "role", v)}
                  testid={`ubo-${i}-role`} placeholder="CEO" />
              </div>
              <div className="col-span-1">
                {data.ubos.length > 1 && (
                  <button type="button" onClick={() => removeUbo(i)}
                    className="h-10 w-full text-xs text-danger hover:bg-danger/10 rounded"
                    data-testid={`ubo-${i}-remove`}>×</button>
                )}
              </div>
            </div>
          ))}
          <button type="button" onClick={addUbo}
            className="text-xs font-mono uppercase tracking-wider text-primary hover:underline"
            data-testid="ubo-add">+ Agregar UBO</button>
        </div>
      </Section>

      <Section title="Caso de uso">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Volumen mensual esperado (USD)" type="number"
            value={data.expected_monthly_volume_usd}
            onChange={(v) => set("expected_monthly_volume_usd", v)}
            testid="volume" placeholder="250000" />
          <Field label="Caso de uso principal" value={data.use_case}
            onChange={(v) => set("use_case", v)}
            testid="use-case" placeholder="Treasury yield, payments..." />
        </div>
      </Section>
    </>
  );
}

/* -------------------- Bits -------------------- */
function Section({ title, icon, children }:
  { title: string; icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section>
      <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-2
                       flex items-center gap-1.5">
        {icon} {title}
      </div>
      <div className="space-y-3 prosper-card p-5">{children}</div>
    </section>
  );
}

function Field({ label, value, onChange, placeholder, type = "text", required, testid }:
  { label: string; value: string; onChange: (v: string) => void;
    placeholder?: string; type?: string; required?: boolean; testid: string }) {
  return (
    <label className="block">
      {label && (
        <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-1">
          {label}
        </div>
      )}
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        required={required}
        data-testid={`apply-${testid}`}
        className="prosper-input w-full h-10 text-sm"
      />
    </label>
  );
}
