"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { ArrowRight, Building2, ChevronLeft, ShieldCheck } from "lucide-react";
import { ProsperLogo } from "@/components/ProsperLogo";
import { api } from "@/lib/api";

interface UBO { full_name: string; ownership_pct: number; role?: string }
interface FormState {
  legal_name: string; commercial_name: string;
  country: string; jurisdiction: string;
  incorporation_date: string; registration_number: string;
  contact_name: string; contact_email: string; contact_phone: string;
  website: string;
  expected_monthly_volume_usd: string;
  use_case: string;
  ubos: UBO[];
}

const initial: FormState = {
  legal_name: "", commercial_name: "",
  country: "", jurisdiction: "",
  incorporation_date: "", registration_number: "",
  contact_name: "", contact_email: "", contact_phone: "",
  website: "",
  expected_monthly_volume_usd: "",
  use_case: "",
  ubos: [{ full_name: "", ownership_pct: 0, role: "" }],
};

/**
 * Legacy public-form flow (no token). Submits to AiPrise via
 * `/v1/onboarding/apply` and redirects to AiPrise hosted UI (or simulator).
 */
export function LegacyApplyForm() {
  const router = useRouter();
  const [form, setForm] = useState<FormState>(initial);
  const [submitting, setSubmitting] = useState(false);

  const setField = (k: keyof FormState, v: string) =>
    setForm((f) => ({ ...f, [k]: v }));
  const setUbo = (i: number, k: keyof UBO, v: string | number) =>
    setForm((f) => ({
      ...f,
      ubos: f.ubos.map((u, idx) => idx === i ? { ...u, [k]: v } : u),
    }));
  const addUbo = () =>
    setForm((f) => ({ ...f, ubos: [...f.ubos, { full_name: "", ownership_pct: 0 }] }));
  const removeUbo = (i: number) =>
    setForm((f) => ({ ...f, ubos: f.ubos.filter((_, idx) => idx !== i) }));

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const body = {
        ...form,
        expected_monthly_volume_usd: form.expected_monthly_volume_usd
          ? Number(form.expected_monthly_volume_usd) : null,
        ubos: form.ubos.filter((u) => u.full_name.trim().length > 0)
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
            className="text-xs font-mono uppercase tracking-wider text-fg-subtle hover:text-fg">
            Already a client? Sign in →
          </Link>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-12">
        <div className="mb-8">
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-1">
            Phase 3 · Onboarding
          </div>
          <h1 className="font-display font-bold text-3xl text-fg tracking-tight">
            Apply to onboard your organization
          </h1>
          <p className="text-sm text-fg-muted mt-2 max-w-xl">
            Tell us about your business. We'll start the KYB verification with our
            licensed partner immediately after submission — typically takes 5
            minutes for the document portion.
          </p>
        </div>

        <form onSubmit={onSubmit} className="space-y-8" data-testid="apply-form">
          <Section title="Company" icon={<Building2 size={14} />}>
            <Field label="Legal name *" value={form.legal_name}
              onChange={(v) => setField("legal_name", v)} testid="legal-name" required />
            <Field label="Commercial name" value={form.commercial_name}
              onChange={(v) => setField("commercial_name", v)} testid="commercial-name" />
            <div className="grid grid-cols-2 gap-3">
              <Field label="Country *" value={form.country} placeholder="AR"
                onChange={(v) => setField("country", v)} testid="country" required />
              <Field label="Jurisdiction *" value={form.jurisdiction}
                placeholder="Buenos Aires"
                onChange={(v) => setField("jurisdiction", v)} testid="jurisdiction" required />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Incorporation date" type="date"
                value={form.incorporation_date}
                onChange={(v) => setField("incorporation_date", v)} testid="incorp-date" />
              <Field label="Registration number" value={form.registration_number}
                onChange={(v) => setField("registration_number", v)} testid="reg-number" />
            </div>
            <Field label="Website" type="url" value={form.website}
              placeholder="https://"
              onChange={(v) => setField("website", v)} testid="website" />
          </Section>

          <Section title="Primary contact" icon={<ShieldCheck size={14} />}>
            <Field label="Full name *" value={form.contact_name}
              onChange={(v) => setField("contact_name", v)} testid="contact-name" required />
            <div className="grid grid-cols-2 gap-3">
              <Field label="Work email *" type="email" value={form.contact_email}
                onChange={(v) => setField("contact_email", v)}
                testid="contact-email" required />
              <Field label="Phone" value={form.contact_phone} placeholder="+54 11 ..."
                onChange={(v) => setField("contact_phone", v)} testid="contact-phone" />
            </div>
          </Section>

          <Section title="Ultimate Beneficial Owners (UBOs)">
            <div className="space-y-3">
              {form.ubos.map((u, i) => (
                <div key={i} className="grid grid-cols-12 gap-2 items-end"
                     data-testid={`ubo-row-${i}`}>
                  <div className="col-span-5">
                    <Field label={i === 0 ? "Full name" : ""} value={u.full_name}
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
                    <Field label={i === 0 ? "Role" : ""} value={u.role || ""}
                      onChange={(v) => setUbo(i, "role", v)}
                      testid={`ubo-${i}-role`} placeholder="CEO" />
                  </div>
                  <div className="col-span-1">
                    {form.ubos.length > 1 && (
                      <button type="button" onClick={() => removeUbo(i)}
                        className="h-10 w-full text-xs text-danger hover:bg-danger/10 rounded"
                        data-testid={`ubo-${i}-remove`}>×</button>
                    )}
                  </div>
                </div>
              ))}
              <button type="button" onClick={addUbo}
                className="text-xs font-mono uppercase tracking-wider text-primary hover:underline"
                data-testid="ubo-add">+ Add UBO</button>
            </div>
          </Section>

          <Section title="Use case">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Expected monthly volume (USD)" type="number"
                value={form.expected_monthly_volume_usd}
                onChange={(v) => setField("expected_monthly_volume_usd", v)}
                testid="volume" placeholder="250000" />
              <Field label="Primary use case" value={form.use_case}
                onChange={(v) => setField("use_case", v)}
                testid="use-case" placeholder="Treasury yield, payments..." />
            </div>
          </Section>

          <div className="flex items-center justify-between border-t border-border pt-6">
            <Link href="/" className="text-xs font-mono uppercase tracking-wider
                                       text-fg-subtle hover:text-fg flex items-center gap-1">
              <ChevronLeft size={12} /> Back
            </Link>
            <button type="submit" disabled={submitting}
              className="prosper-btn-primary h-11 px-6 text-sm gap-2"
              data-testid="apply-submit">
              {submitting ? "Submitting…" : (
                <>Submit & start KYB <ArrowRight size={14} /></>
              )}
            </button>
          </div>
        </form>
      </main>
    </div>
  );
}

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
