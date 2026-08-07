"use client";
import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { ArrowRight } from "lucide-react";
import { ProsperLogo } from "@/components/ProsperLogo";
import { ThemeToggleStandalone } from "@/components/ThemeToggle";

// Diagnostic reasons appended by the Edge middleware / OTP page so the
// user understands WHY they landed back on the login instead of a silent
// loop (tester-reported bug, Jun 2026).
const REASON_MESSAGES: Record<string, string> = {
  "invalid-session":
    "Tu sesión no pudo validarse y fue cerrada. Volvé a ingresar. " +
    "Si esto se repite, el servidor tiene una configuración de sesión " +
    "inconsistente (JWT_SECRET distinto entre frontend y backend).",
  "otp-flow-lost":
    "El flujo del código se perdió (pestaña nueva o sesión de navegación " +
    "reiniciada). Ingresá tu email para pedir un código nuevo.",
};

export default function LoginPage() {
  const router = useRouter();
  const search = useSearchParams();
  const next = search.get("next") || "";   // empty = decide by role post-auth
  const reason = search.get("reason") || "";

  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!reason || !REASON_MESSAGES[reason]) return;
    // Deferred: toasts fired before sonner's <Toaster> hydrates are lost.
    const t = setTimeout(
      () => toast.error(REASON_MESSAGES[reason], { duration: 9000 }), 400);
    return () => clearTimeout(t);
  }, [reason]);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim()) return;
    setLoading(true);
    try {
      const { code, dev_otp, email_status, email_error } =
        await api<{ code: string; dev_otp?: string;
                     email_status?: string; email_error?: string }>(
        "/v1/auth/passwordless-login", {
          method: "POST", body: JSON.stringify({ email: email.trim().toLowerCase() }),
        });
      // Provider rejected the send (e.g. Resend sandbox/domain error).
      // Without a code in the inbox the OTP page is a dead end — surface
      // the provider error and stay here.
      if (email_status === "failed" && !dev_otp) {
        toast.error(
          `No pudimos enviar el email con tu código. Respuesta del proveedor: ${
            email_error || "error desconocido"}`,
          { duration: 12000 });
        return;
      }
      // Stash continuation + email in sessionStorage to bridge to OTP page
      sessionStorage.setItem("prosper_otp_code", code);
      sessionStorage.setItem("prosper_otp_email", email.trim().toLowerCase());
      // In dev/preview the API surfaces the OTP so the user doesn't have to
      // tail the backend log. The OTP page auto-fills the inputs.
      if (dev_otp) sessionStorage.setItem("prosper_otp_dev", dev_otp);
      router.push(`/login/otp?next=${encodeURIComponent(next)}`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not send code");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-bg flex flex-col">
      <header className="px-6 py-5 flex items-center justify-between">
        <ProsperLogo />
        <ThemeToggleStandalone />
      </header>

      <main className="flex-1 flex items-start justify-center px-5 pt-12 sm:pt-20">
        <div className="w-full max-w-[400px]">
          <h1 className="font-display font-bold text-3xl sm:text-4xl text-fg mb-2 leading-tight">
            Ingresá a Prosper
          </h1>
          <p className="text-fg-muted text-sm mb-8">
            Te mandamos un código de 4 dígitos. Sin contraseña.
          </p>

          <form onSubmit={onSubmit} className="space-y-4" data-testid="login-form">
            <div>
              <label className="text-xs font-mono uppercase tracking-wider text-fg-muted mb-2 block">
                Work email
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com"
                className="prosper-input text-base"
                required
                autoFocus
                disabled={loading}
                data-testid="login-email-input"
              />
            </div>

            <button
              type="submit"
              disabled={loading || !email.trim()}
              className="prosper-btn-primary w-full text-base py-3.5"
              data-testid="login-submit-btn"
            >
              {loading ? "Sending code…" : (<>Continue <ArrowRight size={16} /></>)}
            </button>
          </form>

          <p className="text-xs text-fg-subtle mt-8 font-mono uppercase tracking-[0.2em]">
            Encrypted session · 7 day expiry · CNV Regulated
          </p>

          <div className="mt-6 pt-6 border-t border-border space-y-3">
            <a href="/apply"
              data-testid="login-apply-link"
              className="text-sm text-fg flex items-center justify-between gap-2 group">
              <span>
                ¿Primera vez en Prosper?{" "}
                <span className="text-primary font-medium group-hover:underline">
                  Abrí tu cuenta
                </span>
              </span>
              <ArrowRight size={14} className="text-primary
                                                group-hover:translate-x-0.5 transition-transform"/>
            </a>
            <a href="/access"
              data-testid="login-demo-link"
              className="text-[11px] font-mono uppercase tracking-[0.18em] text-fg-subtle
                         hover:text-primary inline-flex items-center gap-1.5">
              <ArrowRight size={11}/> Demo accounts · magic links (preview)
            </a>
          </div>
        </div>
      </main>

      <footer className="px-6 py-4 text-xs text-fg-subtle font-mono uppercase tracking-[0.18em]">
        © prosper · borderless on-chain financial services
      </footer>
    </div>
  );
}
