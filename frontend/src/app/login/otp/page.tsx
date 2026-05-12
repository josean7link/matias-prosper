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
  const next = search.get("next") || "/admin";

  const [digits, setDigits] = useState<string[]>(["", "", "", ""]);
  const [loading, setLoading] = useState(false);
  const [resendIn, setResendIn] = useState(20);
  const [email, setEmail] = useState("");
  const [code, setCode] = useState<string | null>(null);
  const refs = [useRef<HTMLInputElement>(null), useRef<HTMLInputElement>(null),
                useRef<HTMLInputElement>(null), useRef<HTMLInputElement>(null)];

  useEffect(() => {
    const c = sessionStorage.getItem("prosper_otp_code");
    const e = sessionStorage.getItem("prosper_otp_email");
    if (!c || !e) { router.replace("/login"); return; }
    setCode(c); setEmail(e);
    refs[0].current?.focus();
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
      await api("/v1/auth/passwordless-token", {
        method: "POST", body: JSON.stringify({ code, token: otp }),
      });
      sessionStorage.removeItem("prosper_otp_code");
      sessionStorage.removeItem("prosper_otp_email");
      // Hard navigation so middleware re-reads the freshly set cookie
      window.location.href = next;
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
      const { code: newCode } = await api<{ code: string }>("/v1/auth/passwordless-login", {
        method: "POST", body: JSON.stringify({ email }),
      });
      sessionStorage.setItem("prosper_otp_code", newCode);
      setCode(newCode);
      setResendIn(20);
      toast.success("New code sent");
    } catch (err) {
      toast.error("Could not resend");
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
            <ArrowLeft size={14} /> Use a different email
          </button>

          <h1 className="font-display font-bold text-3xl text-fg mb-2 leading-tight">
            Check your email
          </h1>
          <p className="text-fg-muted text-sm mb-8">
            We sent a 4-digit code to{" "}
            <span className="font-mono text-fg">{email || "you"}</span>.
          </p>

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
            {loading ? "Verifying…" : "Verify"}
          </button>

          <div className="mt-6 text-center">
            {resendIn > 0 ? (
              <span className="text-xs text-fg-subtle font-mono">
                Resend code in {resendIn}s
              </span>
            ) : (
              <button
                onClick={resend}
                className="text-xs text-primary font-mono hover:underline"
                data-testid="otp-resend-btn"
              >
                Resend code
              </button>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
