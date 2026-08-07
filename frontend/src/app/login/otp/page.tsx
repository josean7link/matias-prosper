"use client";
import { useState, useRef, useEffect, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { ProsperLogo } from "@/components/ProsperLogo";
import { ThemeToggleStandalone } from "@/components/ThemeToggle";
import { ArrowLeft } from "lucide-react";

export default function OtpPage() {
  const router = useRouter();
  const search = useSearchParams();
  const next = search.get("next") || "";

  const [digits, setDigits] = useState<string[]>(["", "", "", ""]);
  const [loading, setLoading] = useState(false);
  const [resendIn, setResendIn] = useState(20);
  const [email, setEmail] = useState("");
  const [code, setCode] = useState<string | null>(null);
  const [devOtp, setDevOtp] = useState<string | null>(null);
  const refs = [useRef<HTMLInputElement>(null), useRef<HTMLInputElement>(null),
                useRef<HTMLInputElement>(null), useRef<HTMLInputElement>(null)];

  useEffect(() => {
    const c = sessionStorage.getItem("prosper_otp_code");
    const e = sessionStorage.getItem("prosper_otp_email");
    if (!c || !e) { router.replace("/login?reason=otp-flow-lost"); return; }
    setCode(c); setEmail(e);
    const dev = sessionStorage.getItem("prosper_otp_dev");
    if (dev && /^\d{4}$/.test(dev)) {
      // Dev/preview mode: el backend devolvió el OTP porque RESEND_API_KEY
      // no está set. Lo mostramos visible (banner) Y lo pre-cargamos en los
      // inputs, pero NO auto-submiteamos: que el user lo confirme con
      // "Verify" para evitar carreras y dejar visible qué pasó.
      sessionStorage.removeItem("prosper_otp_dev");
      setDevOtp(dev);
      setDigits(dev.split(""));
      refs[3].current?.focus();
    } else {
      refs[0].current?.focus();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (resendIn <= 0) return;
    const t = setTimeout(() => setResendIn((n) => n - 1), 1000);
    return () => clearTimeout(t);
  }, [resendIn]);

  const submit = useCallback(async (otp: string) => {
    if (!code || otp.length !== 4) return;
    setLoading(true);
    try {
      const r = await api<{ accessToken: string; portal?: string; role?: string }>(
        "/v1/auth/passwordless-token", {
          method: "POST", body: JSON.stringify({ code, token: otp }),
        });
      sessionStorage.removeItem("prosper_otp_code");
      sessionStorage.removeItem("prosper_otp_email");
      // Route by ROLE — backend tells us the authoritative portal. Honour
      // the original `?next=` only if it matches the role family;
      // otherwise jump to /admin or /client based on `portal`.
      const authoritative = r.portal === "/admin" ? "/admin" : "/client";
      const next_is_admin   = next.startsWith("/admin");
      const next_is_client  = next.startsWith("/client");
      let dest = authoritative;
      if (authoritative === "/admin" && next_is_admin)   dest = next;
      if (authoritative === "/client" && next_is_client) dest = next;
      // Hard navigation so middleware re-reads the freshly set cookie
      window.location.href = dest;
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Verification failed");
      setDigits(["", "", "", ""]);
      refs[0].current?.focus();
    } finally {
      setLoading(false);
    }
  }, [code, next, refs]);

  const onChange = (i: number, v: string) => {
    if (loading) return;
    const clean = v.replace(/\D/g, "").slice(0, 1);
    const nextDigits = [...digits];
    nextDigits[i] = clean;
    setDigits(nextDigits);
    if (clean && i < 3) refs[i + 1].current?.focus();
    if (nextDigits.every((d) => d) && nextDigits.join("").length === 4) {
      submit(nextDigits.join(""));
    }
  };

  const onKeyDown = (i: number, e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Backspace" && !digits[i] && i > 0) {
      refs[i - 1].current?.focus();
    }
  };

  const onPaste = (e: React.ClipboardEvent<HTMLInputElement>) => {
    const data = e.clipboardData.getData("text").replace(/\D/g, "").slice(0, 4);
    if (data.length < 1) return;
    e.preventDefault();
    const arr = ["", "", "", ""];
    for (let i = 0; i < data.length && i < 4; i++) arr[i] = data[i];
    setDigits(arr);
    refs[Math.min(data.length, 3)].current?.focus();
    if (data.length === 4) submit(data);
  };

  const resend = async () => {
    if (resendIn > 0 || !email) return;
    try {
      const { code: newCode, dev_otp, email_status, email_error } =
        await api<{ code: string; dev_otp?: string;
                     email_status?: string; email_error?: string }>(
        "/v1/auth/passwordless-login", {
          method: "POST", body: JSON.stringify({ email }),
        });
      if (email_status === "failed" && !dev_otp) {
        toast.error(
          `El proveedor de correo rechazó el envío: ${
            email_error || "error desconocido"}`,
          { duration: 12000 });
        return;
      }
      sessionStorage.setItem("prosper_otp_code", newCode);
      setCode(newCode);
      setResendIn(20);
      if (dev_otp && /^\d{4}$/.test(dev_otp)) {
        setDevOtp(dev_otp);
        setDigits(dev_otp.split(""));
      } else {
        setDevOtp(null);
        setDigits(["", "", "", ""]);
      }
      toast.success("Nuevo código enviado");
    } catch (err) {
      toast.error("No pudimos reenviar");
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
          <button
            onClick={() => router.push("/login")}
            className="prosper-btn-ghost text-xs mb-6 -ml-3"
            data-testid="otp-back-btn"
          >
            <ArrowLeft size={14} /> Usar otro email
          </button>

          <h1 className="font-display font-bold text-3xl text-fg mb-2 leading-tight">
            Revisá tu email
          </h1>
          <p className="text-fg-muted text-sm mb-8">
            Te mandamos un código de 4 dígitos a{" "}
            <span className="font-mono text-fg">{email || "vos"}</span>.
          </p>

          {devOtp && (
            <div
              data-testid="otp-dev-banner"
              className="mb-5 rounded-lg border border-warning/40 bg-warning/5 p-4
                          flex items-start gap-3"
            >
              <div className="text-warning text-lg leading-none mt-0.5">⚠</div>
              <div className="text-xs text-fg-muted">
                <strong className="text-fg">Modo demo activo.</strong>{" "}
                El sistema de email no está configurado, así que te mostramos
                el código acá. Tu código es{" "}
                <span className="font-mono text-fg text-base font-bold tracking-widest"
                       data-testid="otp-dev-code">{devOtp}</span>{" "}
                — ya lo pre-cargamos abajo, hacé click en <strong>Verify</strong>.
              </div>
            </div>
          )}

          <div className="flex gap-3 mb-6" data-testid="otp-inputs">
            {digits.map((d, i) => (
              <input
                key={i}
                ref={refs[i]}
                type="text"
                inputMode="numeric"
                pattern="[0-9]*"
                maxLength={1}
                value={d}
                onChange={(e) => onChange(i, e.target.value)}
                onKeyDown={(e) => onKeyDown(i, e)}
                onPaste={onPaste}
                className="w-16 h-16 text-center font-mono text-2xl bg-surface border border-border rounded outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 text-fg"
                disabled={loading}
                data-testid={`otp-digit-${i}`}
              />
            ))}
          </div>

          <button
            onClick={() => submit(digits.join(""))}
            disabled={loading || digits.join("").length !== 4}
            className="prosper-btn-primary w-full text-base py-3.5"
            data-testid="otp-verify-btn"
          >
            {loading ? "Verificando…" : "Verify"}
          </button>

          <div className="mt-6 text-center">
            {resendIn > 0 ? (
              <span className="text-xs text-fg-subtle font-mono">
                Reenviar código en {resendIn}s
              </span>
            ) : (
              <button
                onClick={resend}
                className="text-xs text-primary font-mono hover:underline"
                data-testid="otp-resend-btn"
              >
                Reenviar código
              </button>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
