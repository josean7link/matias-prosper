"use client";
import { notFound } from "next/navigation";
import { useState } from "react";
import { MailCheck } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { KybCard, KybShell, buttonCls, kybEnabled }
  from "../../_components/KybShell";

export default function KybCheckEmailPage() {
  if (!kybEnabled()) notFound();
  const [busy, setBusy] = useState(false);

  async function resend() {
    const email = sessionStorage.getItem("kyb_signup_email");
    if (!email) {
      toast.error("No encontramos tu email. Volvé a empezar desde /kyb/signup.");
      return;
    }
    setBusy(true);
    try {
      await api("/v1/kyb/signup/resend", {
        method: "POST", body: JSON.stringify({ email }),
      });
      toast.success("Listo. Si tu registro está en curso, reenviamos el correo.");
    } catch (err: any) {
      toast.error(err?.message || "No pudimos reenviar el correo");
    } finally {
      setBusy(false);
    }
  }

  return (
    <KybShell>
      <KybCard title="¡Te enviamos un correo!"
               subtitle="Abrí el enlace de activación para confirmar tu cuenta empresarial.">
        <div className="flex justify-center my-6" data-testid="kyb-check-email-icon">
          <div className="h-16 w-16 rounded-full bg-success/10 flex items-center justify-center">
            <MailCheck size={32} className="text-success" />
          </div>
        </div>
        <p className="text-sm text-fg-muted text-center mb-6">
          Si no lo encontrás en tu bandeja de entrada, revisá la carpeta de
          spam o correo no deseado. El enlace vence en 72 horas.
        </p>
        <button onClick={resend} disabled={busy} className={buttonCls}
                data-testid="kyb-resend-email-button">
          {busy ? "Reenviando…" : "Reenviar mail"}
        </button>
      </KybCard>
    </KybShell>
  );
}
