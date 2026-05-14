"use client";
import { useState } from "react";
import { toast } from "sonner";
import {
  ShieldCheck, ShieldOff, KeyRound, AlertTriangle, CheckCircle2,
  Copy, Download, RefreshCw,
} from "lucide-react";
import { Badge } from "@prosper/ui";
import { api } from "@/lib/api";
import {
  type Profile,
  type MfaSetupResponse, type MfaVerifyResponse,
} from "@/lib/profile";

interface Props {
  profile: Profile;
  onUpdated: () => void;
}

type Step = "idle" | "scan" | "verify" | "backup_codes" | "done";

export function SecurityTab({ profile, onUpdated }: Props) {
  return (
    <div className="space-y-6" data-testid="security-tab">
      <MfaSection profile={profile} onUpdated={onUpdated} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// MFA section
// ---------------------------------------------------------------------------
function MfaSection({ profile, onUpdated }: Props) {
  const [setupData, setSetupData]   = useState<MfaSetupResponse | null>(null);
  const [code, setCode]             = useState("");
  const [busy, setBusy]             = useState(false);
  const [step, setStep]             = useState<Step>("idle");
  const [codes, setCodes]           = useState<string[]>([]);
  const [showDisable, setShowDisable] = useState(false);
  const [showRegen, setShowRegen]   = useState(false);

  const startSetup = async () => {
    setBusy(true);
    try {
      const res = await api<MfaSetupResponse>("/v1/client/mfa/setup", { method: "POST" });
      setSetupData(res);
      setStep("scan");
    } catch (err) {
      toast.error((err as Error).message || "No se pudo iniciar el setup");
    } finally { setBusy(false); }
  };

  const verify = async () => {
    if (code.length !== 6) return;
    setBusy(true);
    try {
      const res = await api<MfaVerifyResponse>("/v1/client/mfa/verify", {
        method: "POST",
        body: JSON.stringify({ code }),
      });
      setCodes(res.backup_codes);
      setStep("backup_codes");
      onUpdated();
    } catch (err) {
      toast.error((err as Error).message || "Código inválido");
    } finally { setBusy(false); }
  };

  const reset = () => {
    setSetupData(null);
    setCode("");
    setCodes([]);
    setStep("idle");
  };

  return (
    <section className="prosper-card p-6">
      <div className="flex items-start justify-between gap-4 mb-5">
        <div>
          <h3 className="font-display font-bold text-lg text-fg flex items-center gap-2">
            <ShieldCheck size={18} className={profile.mfa_enabled ? "text-success" : "text-fg-subtle"} />
            Autenticación de dos factores (TOTP)
          </h3>
          <p className="text-xs text-fg-muted mt-1 max-w-md">
            Protege tu cuenta con códigos de un solo uso generados por una app autenticadora
            (Google Authenticator, Authy, 1Password, etc.).
          </p>
        </div>
        {profile.mfa_enabled ? (
          <Badge tone="success" data-testid="mfa-status">Activo</Badge>
        ) : (
          <Badge tone="default" data-testid="mfa-status">Desactivado</Badge>
        )}
      </div>

      {/* IDLE - not enrolled */}
      {!profile.mfa_enabled && step === "idle" && (
        <div className="flex justify-end">
          <button onClick={startSetup} disabled={busy}
            className="prosper-btn-primary h-10 px-4 text-sm gap-1.5 disabled:opacity-50"
            data-testid="mfa-enable-btn">
            <ShieldCheck size={14}/> {busy ? "Generando…" : "Activar MFA"}
          </button>
        </div>
      )}

      {/* SCAN QR */}
      {step === "scan" && setupData && (
        <div className="space-y-5 border-t border-border pt-5" data-testid="mfa-scan-step">
          <div>
            <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-2">
              Paso 1 · Escaneá el QR
            </div>
            <p className="text-xs text-fg-muted mb-3">
              Abrí tu app autenticadora y escaneá este código.
            </p>
            <div className="grid place-items-center bg-white rounded-lg border border-border p-4 max-w-[240px]">
              <img src={setupData.qr_data_url} alt="QR" className="block w-[200px] h-[200px]"
                   data-testid="mfa-qr" />
            </div>
          </div>

          <div>
            <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-1">
              ¿No podés escanear?
            </div>
            <p className="text-xs text-fg-muted mb-2">Ingresá esta clave manualmente:</p>
            <code className="block bg-bg border border-border rounded px-3 py-2 font-mono text-sm break-all"
                  data-testid="mfa-secret-manual">
              {setupData.secret}
            </code>
          </div>

          <div className="flex gap-2">
            <button onClick={reset}
              className="prosper-btn-ghost h-10 px-4 text-sm" data-testid="mfa-cancel">
              Cancelar
            </button>
            <button onClick={() => setStep("verify")}
              className="prosper-btn-primary h-10 px-4 text-sm flex-1"
              data-testid="mfa-scan-continue">
              Ya lo escaneé — Continuar
            </button>
          </div>
        </div>
      )}

      {/* VERIFY CODE */}
      {step === "verify" && (
        <div className="space-y-5 border-t border-border pt-5" data-testid="mfa-verify-step">
          <div>
            <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-2">
              Paso 2 · Confirmá tu app
            </div>
            <p className="text-xs text-fg-muted mb-3">
              Ingresá el código de 6 dígitos que muestra tu app autenticadora.
            </p>
            <OtpInput value={code} onChange={setCode} testid="mfa-code" />
          </div>

          <div className="flex gap-2">
            <button onClick={() => setStep("scan")}
              className="prosper-btn-ghost h-10 px-4 text-sm" data-testid="mfa-back">
              ← Volver al QR
            </button>
            <button onClick={verify} disabled={code.length !== 6 || busy}
              className="prosper-btn-primary h-10 px-4 text-sm flex-1 disabled:opacity-40"
              data-testid="mfa-verify-btn">
              {busy ? "Verificando…" : "Verificar y activar"}
            </button>
          </div>
        </div>
      )}

      {/* BACKUP CODES (one-time view) */}
      {step === "backup_codes" && (
        <BackupCodesView
          codes={codes}
          onDone={() => { reset(); setStep("idle"); }}
        />
      )}

      {/* ACTIVE — show manage actions */}
      {profile.mfa_enabled && step === "idle" && (
        <div className="space-y-3 border-t border-border pt-5">
          <div className="rounded-lg bg-success/5 border border-success/20 p-3 flex items-start gap-3">
            <CheckCircle2 size={16} className="text-success shrink-0 mt-0.5" />
            <p className="text-xs text-fg-muted">
              Tu cuenta está protegida con MFA. Guardá tus códigos de recuperación
              en un gestor de contraseñas — son tu salida de emergencia si perdés
              tu dispositivo.
            </p>
          </div>
          <div className="flex flex-wrap gap-2 justify-end">
            <button onClick={() => setShowRegen(true)}
              className="prosper-btn-ghost h-9 px-3 text-xs gap-1.5"
              data-testid="mfa-regen-btn">
              <RefreshCw size={12}/> Regenerar códigos
            </button>
            <button onClick={() => setShowDisable(true)}
              className="prosper-btn-ghost h-9 px-3 text-xs gap-1.5 text-danger hover:bg-danger/5"
              data-testid="mfa-disable-btn">
              <ShieldOff size={12}/> Desactivar MFA
            </button>
          </div>
        </div>
      )}

      {showDisable && <DisableModal
        onClose={() => setShowDisable(false)}
        onDisabled={() => { setShowDisable(false); onUpdated(); }}
      />}
      {showRegen && <RegenModal
        onClose={() => setShowRegen(false)}
        onRegenerated={(newCodes) => { setCodes(newCodes); setShowRegen(false); setStep("backup_codes"); }}
      />}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Backup codes one-time view
// ---------------------------------------------------------------------------
function BackupCodesView({ codes, onDone }:
  { codes: string[]; onDone: () => void }) {
  const [copied, setCopied] = useState(false);

  const text = codes.join("\n");
  const copy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  const download = () => {
    const blob = new Blob(
      [`Prosper · Códigos de recuperación MFA\n\n${text}\n\nGuardá este archivo en un lugar seguro.`],
      { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "prosper-mfa-backup-codes.txt"; a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-4 border-t border-border pt-5" data-testid="mfa-backup-codes">
      <div className="rounded-lg border border-warning/40 bg-warning/5 p-3 flex items-start gap-3">
        <AlertTriangle size={16} className="text-warning shrink-0 mt-0.5"/>
        <div className="text-xs text-fg-muted">
          <p className="font-medium text-fg">Guardalos ahora — sólo se muestran una vez.</p>
          <p className="mt-0.5">Cada código sirve una sola vez. Si perdés tu app autenticadora,
          usá uno para volver a entrar.</p>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2 bg-bg border border-border rounded-lg p-4">
        {codes.map((c, i) => (
          <div key={c} className="font-mono text-sm flex items-center gap-2"
               data-testid={`backup-code-${i}`}>
            <span className="text-fg-subtle">{(i + 1).toString().padStart(2, "0")}.</span>
            <span className="text-fg">{c}</span>
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        <button onClick={copy}
          className="prosper-btn-ghost flex-1 h-10 px-3 text-sm gap-1.5"
          data-testid="backup-copy">
          <Copy size={13}/> {copied ? "Copiado ✓" : "Copiar"}
        </button>
        <button onClick={download}
          className="prosper-btn-ghost flex-1 h-10 px-3 text-sm gap-1.5"
          data-testid="backup-download">
          <Download size={13}/> Descargar .txt
        </button>
        <button onClick={onDone}
          className="prosper-btn-primary flex-1 h-10 px-3 text-sm"
          data-testid="backup-done">
          Ya los guardé
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Disable & Regen modals
// ---------------------------------------------------------------------------
function DisableModal({ onClose, onDisabled }:
  { onClose: () => void; onDisabled: () => void }) {
  const [code, setCode]   = useState("");
  const [mode, setMode]   = useState<"totp" | "backup">("totp");
  const [backup, setBack] = useState("");
  const [busy, setBusy]   = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      await api("/v1/client/mfa/disable", {
        method: "POST",
        body: JSON.stringify(
          mode === "totp" ? { code } : { backup_code: backup }),
      });
      toast.success("MFA desactivado");
      onDisabled();
    } catch (err) {
      toast.error((err as Error).message || "Código inválido");
    } finally { setBusy(false); }
  };

  return (
    <Modal onClose={onClose} testid="mfa-disable-modal">
      <div className="flex items-center gap-2 mb-3">
        <ShieldOff size={16} className="text-danger"/>
        <h2 className="font-display font-bold text-lg text-fg">Desactivar MFA</h2>
      </div>
      <p className="text-xs text-fg-muted mb-4">
        Para desactivar MFA necesitamos verificar que sos vos. Usá tu app
        autenticadora o un código de recuperación.
      </p>

      <div className="grid grid-cols-2 gap-2 mb-4">
        {(["totp", "backup"] as const).map((m) => (
          <button key={m} onClick={() => setMode(m)}
            className={`p-2.5 rounded border text-center text-xs transition-all
              ${mode === m ? "border-primary bg-primary/5 ring-1 ring-primary" :
                              "border-border hover:bg-surface-hover"}`}
            data-testid={`mfa-disable-mode-${m}`}>
            {m === "totp" ? "Código TOTP" : "Backup code"}
          </button>
        ))}
      </div>

      {mode === "totp" ? (
        <OtpInput value={code} onChange={setCode} testid="mfa-disable-code" />
      ) : (
        <input value={backup} onChange={(e) => setBack(e.target.value.toUpperCase())}
          maxLength={11}
          placeholder="XXXX-XXXX"
          className="prosper-input w-full h-10 text-sm font-mono"
          data-testid="mfa-disable-backup" />
      )}

      <div className="flex gap-2 mt-5">
        <button onClick={onClose}
          className="prosper-btn-ghost flex-1 h-10 text-sm" data-testid="mfa-disable-cancel">
          Cancelar
        </button>
        <button onClick={submit}
          disabled={busy || (mode === "totp" ? code.length !== 6 : backup.length < 8)}
          className="prosper-btn-primary flex-1 h-10 text-sm disabled:opacity-40 bg-danger hover:bg-danger/90"
          data-testid="mfa-disable-confirm">
          {busy ? "Desactivando…" : "Desactivar"}
        </button>
      </div>
    </Modal>
  );
}

function RegenModal({ onClose, onRegenerated }:
  { onClose: () => void; onRegenerated: (codes: string[]) => void }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      const res = await api<{ ok: true; backup_codes: string[] }>(
        "/v1/client/mfa/regenerate-codes",
        { method: "POST", body: JSON.stringify({ code }) });
      onRegenerated(res.backup_codes);
    } catch (err) {
      toast.error((err as Error).message || "Código inválido");
    } finally { setBusy(false); }
  };

  return (
    <Modal onClose={onClose} testid="mfa-regen-modal">
      <div className="flex items-center gap-2 mb-3">
        <RefreshCw size={16} className="text-primary"/>
        <h2 className="font-display font-bold text-lg text-fg">Regenerar códigos de recuperación</h2>
      </div>
      <p className="text-xs text-fg-muted mb-4">
        Los códigos anteriores van a dejar de funcionar inmediatamente.
        Confirmá con tu código TOTP actual.
      </p>
      <OtpInput value={code} onChange={setCode} testid="mfa-regen-code" />
      <div className="flex gap-2 mt-5">
        <button onClick={onClose}
          className="prosper-btn-ghost flex-1 h-10 text-sm" data-testid="mfa-regen-cancel">
          Cancelar
        </button>
        <button onClick={submit} disabled={busy || code.length !== 6}
          className="prosper-btn-primary flex-1 h-10 text-sm disabled:opacity-40"
          data-testid="mfa-regen-confirm">
          {busy ? "Generando…" : "Regenerar"}
        </button>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Shared bits
// ---------------------------------------------------------------------------
function OtpInput({ value, onChange, testid }:
  { value: string; onChange: (v: string) => void; testid: string }) {
  return (
    <input
      value={value}
      onChange={(e) => onChange(e.target.value.replace(/\D/g, "").slice(0, 6))}
      inputMode="numeric" autoComplete="one-time-code"
      maxLength={6}
      placeholder="000000"
      className="prosper-input w-full h-12 text-center text-xl font-mono tracking-[0.4em]"
      data-testid={testid} />
  );
}

function Modal({ children, onClose, testid }:
  { children: React.ReactNode; onClose: () => void; testid: string }) {
  return (
    <div className="fixed inset-0 bg-bg/70 backdrop-blur-sm z-50 grid place-items-center p-4"
         onClick={onClose}
         data-testid={testid}>
      <div className="prosper-card p-6 w-full max-w-md"
           onClick={(e) => e.stopPropagation()}>
        {children}
      </div>
    </div>
  );
}
