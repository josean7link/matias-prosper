"use client";
import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { ArrowRight } from "lucide-react";
import { ProsperLogo } from "@/components/ProsperLogo";
import { ThemeToggleStandalone } from "@/components/ThemeToggle";

export default function LoginPage() {
  const router = useRouter();
  const search = useSearchParams();
  const next = search.get("next") || "/admin";

  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim()) return;
    setLoading(true);
    try {
      const { code } = await api<{ code: string }>("/v1/auth/passwordless-login", {
        method: "POST", body: JSON.stringify({ email: email.trim().toLowerCase() }),
      });
      // Stash continuation + email in sessionStorage to bridge to OTP page
      sessionStorage.setItem("prosper_otp_code", code);
      sessionStorage.setItem("prosper_otp_email", email.trim().toLowerCase());
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
            Sign in to Prosper
          </h1>
          <p className="text-fg-muted text-sm mb-8">
            We&apos;ll email you a 4-digit code. No password needed.
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
        </div>
      </main>

      <footer className="px-6 py-4 text-xs text-fg-subtle">
        © Prosper Foundation · Tokenized yield on Stellar
      </footer>
    </div>
  );
}
