"use client";
import { notFound, useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { KybCard, KybShell, buttonCls, inputCls, labelCls, kybEnabled }
  from "../_components/KybShell";

export default function KybSignupPage() {
  if (!kybEnabled()) notFound();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [company, setCompany] = useState("");
  const [busy, setBusy] = useState(false);
  const [resumeHint, setResumeHint] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await api<{ signup_token: string }>("/v1/kyb/signup/start", {
        method: "POST",
        body: JSON.stringify({ email, company_name: company }),
      });
      sessionStorage.setItem("kyb_signup_token", r.signup_token);
      sessionStorage.setItem("kyb_signup_email", email);
      router.push("/kyb/signup/contact");
    } catch (err: any) {
      toast.error(err?.message || "No pudimos iniciar el registro");
    } finally {
      setBusy(false);
    }
  }

  return (
    <KybShell step="Paso 1 de 3">
      <KybCard title="Creá tu cuenta empresarial"
               subtitle="Registrá tu organización para operar con los fondos PROSPER ARS y PROSPER USD.">
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className={labelCls} htmlFor="kyb-email">Email corporativo</label>
            <input id="kyb-email" data-testid="kyb-signup-email-input"
                   type="email" required value={email} className={inputCls}
                   placeholder="nombre@tuempresa.com"
                   onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div>
            <label className={labelCls} htmlFor="kyb-company">Nombre de la empresa</label>
            <input id="kyb-company" data-testid="kyb-signup-company-input"
                   type="text" required minLength={2} value={company}
                   className={inputCls} placeholder="Razón social o nombre comercial"
                   onChange={(e) => setCompany(e.target.value)} />
          </div>
          <button type="submit" disabled={busy} className={buttonCls}
                  data-testid="kyb-signup-submit-button">
            {busy ? "Procesando…" : "Avanzar"}
          </button>
        </form>
      </KybCard>
      <p className="text-center text-sm text-fg-muted mt-6">
        Continuá la creación de cuenta empresarial —{" "}
        <button type="button" data-testid="kyb-signup-resume-link"
                className="text-primary hover:underline"
                onClick={() => setResumeHint(true)}>
          hacé click acá para retomar el proceso
        </button>
      </p>
      {resumeHint && (
        <p className="text-center text-xs text-fg-muted mt-2 bg-surface border border-border rounded-lg p-3"
           data-testid="kyb-signup-resume-hint">
          Ingresá arriba el mismo email con el que empezaste: retomamos tu
          trámite exactamente donde lo dejaste, sin duplicarlo. Si ya habías
          finalizado los tres pasos, te reenviamos el correo de activación.
        </p>
      )}
    </KybShell>
  );
}
