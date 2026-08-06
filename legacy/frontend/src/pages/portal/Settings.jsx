import { useEffect, useState } from "react";
import api from "@/lib/api";
import { useApp } from "@/contexts/AppContext";
import { PageHeader, EnvPill, StatusBadge } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { ShieldCheck, Warning } from "@phosphor-icons/react";
import { toast } from "sonner";

export default function PortalSettings() {
  const { user, env, checkAuth } = useApp();
  const [mfaSetupOpen, setMfaSetupOpen] = useState(false);
  const [setupData, setSetupData] = useState(null);
  const [verifyCode, setVerifyCode] = useState("");
  const [disableOpen, setDisableOpen] = useState(false);
  const [disableCode, setDisableCode] = useState("");

  const startMfa = async () => {
    const { data } = await api.post("/auth/mfa/enable");
    setSetupData(data);
    setMfaSetupOpen(true);
  };

  const verify = async () => {
    try {
      await api.post("/auth/mfa/verify", { code: verifyCode });
      toast.success("MFA enabled");
      setMfaSetupOpen(false); setSetupData(null); setVerifyCode("");
      checkAuth();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Invalid code");
    }
  };

  const disable = async () => {
    try {
      await api.post("/auth/mfa/disable", { code: disableCode });
      toast.success("MFA disabled");
      setDisableOpen(false); setDisableCode("");
      checkAuth();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Invalid code");
    }
  };

  return (
    <div data-testid="portal-settings">
      <PageHeader title="Settings" subtitle="Personal & organization preferences" />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 max-w-4xl">
        {/* Account */}
        <div className="prosper-card p-6">
          <div className="text-[10px] uppercase tracking-wider text-[var(--fg-muted)] mb-2">Signed in as</div>
          <div className="flex items-center gap-3 mb-6">
            {user?.picture && <img src={user.picture} alt="" className="w-12 h-12 rounded-full border border-[var(--border)]" />}
            <div>
              <div className="font-semibold text-[var(--fg)]">{user?.name}</div>
              <div className="font-mono text-xs text-[var(--fg-muted)]">{user?.email}</div>
            </div>
          </div>
          <div className="space-y-2 text-sm">
            <Row label="Role" value={<span className="uppercase font-mono text-xs">{user?.platform_role}</span>} />
            <Row label="Environment" value={<EnvPill env={env} />} />
            <Row label="Internal staff" value={user?.is_internal ? "yes" : "no"} />
          </div>
        </div>

        {/* MFA */}
        <div className="prosper-card p-6">
          <div className="flex items-center gap-2 mb-3">
            <ShieldCheck size={18} weight="fill" style={{ color: user?.mfa_enabled ? "var(--success)" : "var(--fg-muted)" }} />
            <div className="font-display font-bold text-lg">Two-Factor Authentication</div>
          </div>
          <p className="text-sm text-[var(--fg-muted)] mb-4">
            Protect your account with TOTP codes from an authenticator app (Google Authenticator, 1Password, Authy).
            Required when approving sensitive operations.
          </p>
          {user?.mfa_enabled ? (
            <div className="flex items-center justify-between">
              <StatusBadge value="active" />
              <Button variant="outline" onClick={() => setDisableOpen(true)} data-testid="mfa-disable-btn"
                      className="rounded-full border-[var(--danger)]/40 text-[var(--danger)]">
                Disable
              </Button>
            </div>
          ) : (
            <Button onClick={startMfa} data-testid="mfa-enable-btn"
                    className="rounded-full bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white gap-1.5">
              <ShieldCheck size={14} weight="bold" /> Enable MFA
            </Button>
          )}
        </div>
      </div>

      {/* Setup MFA dialog */}
      <Dialog open={mfaSetupOpen} onOpenChange={setMfaSetupOpen}>
        <DialogContent className="max-w-md bg-[var(--surface)] border-[var(--border)] rounded-xl" data-testid="mfa-setup-dialog">
          <DialogHeader>
            <DialogTitle className="font-display">Set up Authenticator</DialogTitle>
          </DialogHeader>
          {setupData && (
            <div className="space-y-4">
              <ol className="text-sm space-y-1 list-decimal list-inside text-[var(--fg-muted)]">
                <li>Scan the QR below with your authenticator app.</li>
                <li>Or enter the secret manually: <span className="font-mono text-[var(--fg)] text-xs break-all">{setupData.secret}</span></li>
                <li>Enter the 6-digit code to verify.</li>
              </ol>
              <div className="bg-white rounded-xl p-4 border border-[var(--border)] flex justify-center">
                <img src={setupData.qr_code_data_url} alt="MFA QR" className="w-48 h-48" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs uppercase tracking-wider text-[var(--fg-muted)]">Verification code</Label>
                <Input value={verifyCode} onChange={(e) => setVerifyCode(e.target.value)}
                       placeholder="123 456"
                       className="bg-[var(--bg)] border-[var(--border)] font-mono text-center text-lg tracking-[0.5em] rounded-md"
                       maxLength={6} data-testid="mfa-verify-code" />
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" className="rounded-full" onClick={() => setMfaSetupOpen(false)}>Cancel</Button>
            <Button onClick={verify} disabled={verifyCode.length !== 6}
                    className="rounded-full bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white"
                    data-testid="mfa-verify-btn">Verify & Enable</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Disable dialog */}
      <Dialog open={disableOpen} onOpenChange={setDisableOpen}>
        <DialogContent className="max-w-md bg-[var(--surface)] border-[var(--border)] rounded-xl">
          <DialogHeader>
            <DialogTitle className="font-display flex items-center gap-2">
              <Warning size={18} weight="fill" style={{ color: "var(--warning)" }} /> Disable MFA
            </DialogTitle>
          </DialogHeader>
          <p className="text-sm text-[var(--fg-muted)]">Enter a current TOTP code to disable.</p>
          <Input value={disableCode} onChange={(e) => setDisableCode(e.target.value)}
                 placeholder="123 456"
                 className="bg-[var(--bg)] border-[var(--border)] font-mono text-center text-lg tracking-[0.5em] rounded-md"
                 maxLength={6} data-testid="mfa-disable-code" />
          <DialogFooter>
            <Button variant="outline" className="rounded-full" onClick={() => setDisableOpen(false)}>Cancel</Button>
            <Button onClick={disable} className="rounded-full text-white" style={{ background: "var(--danger)" }}
                    data-testid="mfa-disable-confirm">Disable</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

const Row = ({ label, value }) => (
  <div className="flex justify-between py-2 border-b border-[var(--border)] last:border-0">
    <span className="text-[var(--fg-muted)] text-xs uppercase tracking-wider">{label}</span>
    <span>{value}</span>
  </div>
);
