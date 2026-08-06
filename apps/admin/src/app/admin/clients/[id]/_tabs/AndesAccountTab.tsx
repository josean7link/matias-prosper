"use client";
import { useState } from "react";
import { Badge } from "@prosper/ui";
import {
  Wallet, Banknote, RefreshCw, Copy, AlertTriangle,
  CheckCircle2, Clock, ArrowDownToLine, Link2, Edit3, Save, X,
  Send, ArrowRight,
} from "lucide-react";
import { toast } from "sonner";
import {
  useRampAccounts, useRampBalances,
  createRampAccount, retryRampAccount, refreshWalletStatus,
  fmtArsa, shortCvu, chainLabel, explorerUrl, type OnboardingStatus,
} from "@/lib/ramp";
import {
  useAccountArsaChain, setAccountArsaChain, executeTransfer,
} from "@/lib/admin-ramp";

const STATUS_TONE: Record<OnboardingStatus,
  "success" | "info" | "warning" | "danger" | "auto"> = {
  approved:           "success",
  pending_approval:   "info",
  kyc_pending_andes:  "warning",
  rejected:           "danger",
  error:              "danger",
};

const STATUS_LABEL: Record<OnboardingStatus, string> = {
  approved:           "Aprobada",
  pending_approval:   "Pendiente",
  kyc_pending_andes:  "Falta KYC Andes",
  rejected:           "Rechazada",
  error:              "Error",
};

export default function AndesAccountTab({ orgId }: { orgId: string }) {
  const { data: accounts, isLoading, mutate } = useRampAccounts(orgId);
  const [creating, setCreating] = useState(false);
  const [retrying, setRetrying] = useState<string | null>(null);

  // For Phase 14 we expect a single account whose end_customer_id == org_id.
  const acc = (accounts ?? []).find(a => a.end_customer_id === orgId)
              ?? (accounts ?? [])[0];

  const handleCreate = async () => {
    setCreating(true);
    try {
      const res = await createRampAccount({ end_customer_id: orgId }, orgId);
      toast.success(
        res.onboarding_status === "approved"
          ? "Cuenta Andes creada y aprobada"
          : "Cuenta Andes creada · " + (STATUS_LABEL[res.onboarding_status] || res.onboarding_status));
      await mutate();
    } catch (e: any) {
      toast.error(e?.message || "No se pudo crear la cuenta Andes");
    } finally { setCreating(false); }
  };

  const handleRetry = async (ecid: string) => {
    setRetrying(ecid);
    try {
      const res = await retryRampAccount(ecid, orgId);
      toast.success(`Reintento → ${STATUS_LABEL[res.onboarding_status] || res.onboarding_status}`);
      await mutate();
    } catch (e: any) {
      toast.error(e?.message || "No se pudo reintentar");
    } finally { setRetrying(null); }
  };

  const copy = async (v: string | null, label: string) => {
    if (!v) return;
    try { await navigator.clipboard?.writeText(v); toast.success(`${label} copiado`); }
    catch { toast.error("No se pudo copiar"); }
  };

  return (
    <div data-testid="tab-content-andes" className="space-y-5">
      {/* Header + action */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
            Provider Andeslabs
          </div>
          <h3 className="font-display font-bold text-lg text-fg flex items-center gap-1.5 mt-0.5">
            <Wallet size={16} className="text-primary"/> Cuenta de pesos digitales · ARSa
          </h3>
          <p className="text-xs text-fg-muted mt-1 max-w-xl">
            Cada cliente tiene una cuenta dedicada en Andes con un CVU propio y
            una wallet ARSa (activo clásico de Stellar, code ARSa). Las
            cuentas se crean automáticamente al aprobar el KYB; las wallets
            Stellar se aprovisionan en estado <strong>pending</strong> y pasan a
            <strong> active</strong> vía el webhook <code>wallet.active</code>.
            Si falta el KYC de Andes el CVU queda pendiente y se puede
            reintentar acá.
          </p>
        </div>
        {!acc && (
          <button
            data-testid="andes-create-btn"
            onClick={handleCreate}
            disabled={creating}
            className="prosper-btn-primary h-9 text-xs gap-1.5">
            <Banknote size={12}/> {creating ? "Creando…" : "Crear cuenta Andes"}
          </button>
        )}
      </div>

      {/* Empty state */}
      {isLoading && (
        <div className="prosper-card p-6 text-center text-fg-subtle text-xs">
          Cargando cuenta Andes…
        </div>
      )}
      {!isLoading && !acc && (
        <div className="prosper-card p-6 text-center" data-testid="andes-empty">
          <div className="mx-auto mb-2 h-10 w-10 rounded-full bg-warning/10 flex items-center justify-center">
            <AlertTriangle size={18} className="text-warning"/>
          </div>
          <div className="text-sm font-display font-semibold text-fg">
            Sin cuenta Andes
          </div>
          <p className="text-xs text-fg-muted mt-1">
            Este cliente todavía no tiene una cuenta Andes provisionada.
            Crear una habilita el alta de CVU y wallet ARSa.
          </p>
        </div>
      )}

      {/* Account card */}
      {acc && (
        <div className="prosper-card p-5 space-y-4" data-testid="andes-account-card">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-2 flex-wrap">
              <Badge tone={STATUS_TONE[acc.onboarding_status] || "auto"}
                     data-testid="andes-status-badge">
                {STATUS_LABEL[acc.onboarding_status] || acc.onboarding_status}
              </Badge>
              <Badge tone="auto" size="sm">CVU · {acc.cvu_status}</Badge>
              {acc.wallet_status && (
                <Badge
                  data-testid="andes-wallet-status-badge"
                  tone={acc.wallet_status === "active" ? "success" : "warning"}
                  size="sm">
                  Wallet · {acc.wallet_status === "active" ? "Activa" : "Activando"}
                </Badge>
              )}
              <span className="text-[10px] font-mono text-fg-subtle">
                provider: {acc.provider}
              </span>
            </div>
            <div className="flex gap-2">
              <WalletRefreshButton
                endCustomerId={acc.end_customer_id} orgId={orgId}
                onRefreshed={() => mutate()}/>
              <button
                data-testid="andes-retry-btn"
                onClick={() => handleRetry(acc.end_customer_id)}
                disabled={retrying === acc.end_customer_id}
                className="prosper-btn-ghost h-8 text-[11px] gap-1.5">
                <RefreshCw size={11}
                  className={retrying === acc.end_customer_id ? "animate-spin" : ""}/>
                {acc.onboarding_status === "approved"
                  ? "Re-crear / refrescar"
                  : "Reintentar / completar KYC"}
              </button>
            </div>
          </div>

          {acc.onboarding_message && (
            <div className="rounded border border-warning/40 bg-warning/5 text-warning text-[11px] px-3 py-2 leading-snug"
                 data-testid="andes-onboarding-message">
              {acc.onboarding_message}
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
            <KV label="End customer" value={acc.end_customer_id} mono
                testid="andes-end-customer-id"/>
            <KV label="Andes userId" value={acc.provider_user_id || "—"} mono
                testid="andes-provider-user-id"
                onCopy={() => copy(acc.provider_user_id, "userId")}/>
            <KV label="CVU" value={shortCvu(acc.cvu)} mono
                testid="andes-cvu"
                onCopy={acc.cvu ? () => copy(acc.cvu, "CVU") : undefined}
                icon={acc.cvu
                  ? <CheckCircle2 size={11} className="text-success"/>
                  : <Clock size={11} className="text-fg-subtle"/>}/>
            <KV label="Alias" value={acc.alias || "—"} mono
                testid="andes-alias"
                onCopy={acc.alias ? () => copy(acc.alias, "alias") : undefined}/>
            <KV label={`Wallet ARSa (${chainLabel(acc.wallet_chain)})`}
                value={acc.wallet_address || "—"} mono small
                testid="andes-wallet-address"
                onCopy={acc.wallet_address
                  ? () => copy(acc.wallet_address, "address") : undefined}
                explorerHref={explorerUrl(acc.wallet_chain, acc.wallet_address)}/>
            {acc.wallet_activated_at && (
              <KV label="Wallet activada" mono small
                  testid="andes-wallet-activated-at"
                  value={new Date(acc.wallet_activated_at).toLocaleString()}/>
            )}
            <KV label="Creada" value={new Date(acc.created_at).toLocaleString()}
                testid="andes-created-at"/>
          </div>

          <BalanceTable endCustomerId={acc.end_customer_id} orgId={orgId}/>

          <TransferActionRow endCustomerId={acc.end_customer_id} orgId={orgId}
                                onTransferred={() => mutate()}/>

          <ChainSelectorRow endCustomerId={acc.end_customer_id} orgId={orgId}/>
        </div>
      )}
    </div>
  );
}

function KV({ label, value, mono, small, icon, onCopy, testid,
                 explorerHref }: {
  label: string; value: string; mono?: boolean; small?: boolean;
  icon?: React.ReactNode; onCopy?: () => void; testid?: string;
  explorerHref?: string | null;
}) {
  return (
    <div className="flex items-start gap-2 py-1 border-b border-border/40 last:border-0">
      <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle min-w-[120px] pt-0.5">
        {label}
      </div>
      <div className={`flex-1 ${mono ? "font-mono" : ""} ${small ? "text-[10px]" : "text-xs"} break-all text-fg`}
           data-testid={testid}>
        <span className="inline-flex items-center gap-1">
          {icon} {value}
        </span>
      </div>
      {onCopy && (
        <button onClick={onCopy} className="text-fg-subtle hover:text-fg"
                aria-label={`Copiar ${label}`}>
          <Copy size={11}/>
        </button>
      )}
      {explorerHref && (
        <a href={explorerHref} target="_blank" rel="noopener noreferrer"
           className="text-fg-subtle hover:text-primary"
           aria-label="Ver en explorer"
           data-testid={testid ? `${testid}-explorer` : undefined}>
          <Link2 size={11}/>
        </a>
      )}
    </div>
  );
}

function WalletRefreshButton({ endCustomerId, orgId, onRefreshed }: {
  endCustomerId: string; orgId: string; onRefreshed: () => void;
}) {
  const [busy, setBusy] = useState(false);
  return (
    <button
      data-testid="andes-wallet-refresh-btn"
      onClick={async () => {
        setBusy(true);
        try {
          const r = await refreshWalletStatus(endCustomerId, orgId);
          toast.success(
            r.wallet_status === "active"
              ? "Wallet activa"
              : "Wallet sigue activándose");
          onRefreshed();
        } catch (e: any) {
          toast.error(e?.message || "No se pudo refrescar estado");
        } finally { setBusy(false); }
      }}
      disabled={busy}
      className="prosper-btn-ghost h-8 text-[11px] gap-1.5">
      <RefreshCw size={11} className={busy ? "animate-spin" : ""}/>
      Refrescar estado wallet
    </button>
  );
}

function BalanceTable({ endCustomerId, orgId }: { endCustomerId: string; orgId: string }) {
  const { data, isLoading } = useRampBalances(endCustomerId, orgId);
  // Show one row per (asset, chain) — ARSa-stellar and ARSa-base must not be
  // summed together; they are distinct tokens.
  return (
    <div className="pt-2">
      <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-2 flex items-center gap-1.5">
        <ArrowDownToLine size={11}/> Saldos por activo y red
      </div>
      <table className="w-full text-xs" data-testid="andes-balances-table">
        <thead>
          <tr className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle border-b border-border">
            <th className="text-left py-1.5">Asset</th>
            <th className="text-left py-1.5">Red</th>
            <th className="text-right py-1.5">Saldo</th>
            <th className="text-left py-1.5 pl-3">Nota</th>
          </tr>
        </thead>
        <tbody>
          {isLoading && (
            <tr><td colSpan={4} className="py-3 text-center text-fg-subtle italic">
              Cargando…
            </td></tr>
          )}
          {(data?.items ?? []).map((b, i) => (
            <tr key={`${b.asset_code}-${b.chain}-${i}`}
                className="border-b border-border/40"
                data-testid={`andes-balance-row-${b.asset_code}-${b.chain}`}>
              <td className="py-1.5">
                <span className="inline-flex items-center gap-1.5 font-display font-bold text-fg">
                  {b.asset_label}
                </span>
              </td>
              <td className="py-1.5">
                <Badge tone={b.chain === "stellar" ? "info" : "warning"} size="sm">
                  {b.chain === "stellar" ? "Stellar" :
                   b.chain === "base"    ? "Base"    : b.chain}
                </Badge>
              </td>
              <td className="py-1.5 text-right font-mono tabular text-fg">
                {b.asset_code === "arsa"
                  ? fmtArsa(b.amount)
                  : `${b.asset_symbol} ${b.amount}`}
              </td>
              <td className="py-1.5 pl-3 text-fg-subtle text-[10px]">
                {b.asset_caption}
              </td>
            </tr>
          ))}
          {!isLoading && (data?.items ?? []).length === 0 && (
            <tr><td colSpan={4} className="py-3 text-center text-fg-subtle italic">
              Sin saldos todavía.
            </td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

// ─────────────────────────────────────────────────────── Phase 17 chain override
function ChainSelectorRow({ endCustomerId, orgId }:
                              { endCustomerId: string; orgId: string }) {
  const { data, mutate, isLoading } = useAccountArsaChain(endCustomerId, orgId);
  const [editing, setEditing] = useState(false);
  const [picked, setPicked]   =
    useState<"stellar" | "base" | "default">("default");
  const [busy, setBusy]       = useState(false);

  if (isLoading || !data) {
    return (
      <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle pt-1">
        Cadena ARSa · cargando…
      </div>
    );
  }

  const openEditor = () => {
    setPicked(data.override ?? "default");
    setEditing(true);
  };
  const save = async () => {
    setBusy(true);
    try {
      const ov = picked === "default" ? null : picked;
      await setAccountArsaChain(endCustomerId, { override: ov }, orgId);
      toast.success(
        ov ? `Cuenta fijada en red ${ov}` : "Override eliminado · usa default del org");
      setEditing(false);
      await mutate();
    } catch (e: any) {
      toast.error(e?.message || "No se pudo guardar");
    } finally { setBusy(false); }
  };

  return (
    <div className="pt-3 border-t border-border/60"
         data-testid="andes-chain-selector">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
            Red ARSa de esta cuenta
          </div>
          <div className="flex items-center gap-2 mt-1">
            <Badge
              tone={data.effective_chain === "stellar" ? "info" : "warning"}
              data-testid="andes-chain-effective">
              <Link2 size={10} className="mr-1"/>
              {data.effective_chain === "stellar" ? "Stellar" : "Base"}
            </Badge>
            <span className="text-[10px] font-mono text-fg-subtle"
                  data-testid="andes-chain-source">
              {data.source === "account_override"
                ? "override por cuenta"
                : data.source === "global"
                  ? "default global"
                  : data.source === "org_override"
                    ? "default del org"
                    : "default por defecto"}
            </span>
          </div>
        </div>
        {!editing && (
          <button onClick={openEditor}
                  data-testid="andes-chain-edit-btn"
                  className="prosper-btn-ghost h-8 text-[11px] gap-1.5">
            <Edit3 size={11}/> Cambiar red
          </button>
        )}
      </div>

      {data.has_wallet_on_other_chain && (
        <div className="mt-2 rounded border border-warning/30 bg-warning/5 px-3 py-2 text-[11px] text-fg leading-snug"
             data-testid="andes-chain-warn-existing">
          <AlertTriangle size={11} className="inline mr-1 text-warning"/>
          Esta cuenta ya tiene una wallet ARSa en red{" "}
          <strong>{data.wallet_chain}</strong>. Cambiar la red crea una nueva
          wallet ARSa en la red elegida — el saldo de la red anterior no se
          mueve.
        </div>
      )}

      {editing && (
        <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-2">
          <ChainOpt testid="andes-chain-opt-default"
            label="Usar default del org"
            picked={picked === "default"}
            onClick={() => setPicked("default")}/>
          <ChainOpt testid="andes-chain-opt-stellar"
            label="Stellar"
            picked={picked === "stellar"}
            onClick={() => setPicked("stellar")}/>
          <ChainOpt testid="andes-chain-opt-base"
            label="Base"
            picked={picked === "base"}
            onClick={() => setPicked("base")}/>
          <div className="md:col-span-3 flex justify-end gap-2 pt-1">
            <button onClick={() => setEditing(false)}
                    className="prosper-btn-ghost h-8 text-[11px]">
              <X size={11}/> Cancelar
            </button>
            <button onClick={save} disabled={busy}
                    data-testid="andes-chain-save-btn"
                    className="prosper-btn-primary h-8 text-[11px] gap-1.5">
              <Save size={11}/> Guardar
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function ChainOpt({ label, picked, onClick, testid }:
                      { label: string; picked: boolean;
                        onClick: () => void; testid: string }) {
  return (
    <button onClick={onClick} data-testid={testid}
            className={`text-left rounded border px-3 py-2 transition-colors text-[11px] ${
              picked
                ? "border-primary bg-primary/5 text-fg"
                : "border-border bg-surface text-fg hover:border-primary/40"}`}>
      <div className="flex items-center gap-1.5">
        {picked
          ? <CheckCircle2 size={12} className="text-primary"/>
          : <div className="h-2.5 w-2.5 rounded-full border border-border"/>}
        {label}
      </div>
    </button>
  );
}

// ─────────────────────────────────────────── Phase 15.2 — Crypto transfer
function TransferActionRow({ endCustomerId, orgId, onTransferred }: {
  endCustomerId: string; orgId: string; onTransferred: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="pt-3 border-t border-border/60"
         data-testid="andes-transfer-section">
      <div className="flex items-center justify-between gap-2">
        <div>
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
            Transferencia cripto (wallet → wallet)
          </div>
          <div className="text-[11px] text-fg-muted mt-1">
            Mover ARSa / USDT / USDC a otra wallet en la misma red.
          </div>
        </div>
        <button onClick={() => setOpen(true)}
                data-testid="andes-transfer-open-btn"
                className="prosper-btn-ghost h-8 text-[11px] gap-1.5">
          <Send size={11}/> Transferir
        </button>
      </div>
      {open && (
        <TransferModal endCustomerId={endCustomerId} orgId={orgId}
          onClose={() => setOpen(false)}
          onSuccess={() => { setOpen(false); onTransferred(); }}/>
      )}
    </div>
  );
}

function TransferModal({ endCustomerId, orgId, onClose, onSuccess }: {
  endCustomerId: string; orgId: string;
  onClose: () => void; onSuccess: () => void;
}) {
  const [asset, setAsset]     = useState<"arsa" | "usdc" | "usdt">("arsa");
  const [chain, setChain]     = useState<"stellar" | "base">("stellar");
  const [amount, setAmount]   = useState("");
  const [toAddress, setToAddr] = useState("");
  const [memo, setMemo]       = useState("");
  const [busy, setBusy]       = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      const idem = "ik_tr_" + Date.now();
      await executeTransfer(endCustomerId, {
        asset, chain, amount, to_address: toAddress,
        memo: memo || undefined,
      }, orgId, idem);
      toast.success("Transferencia enviada · esperando webhook");
      onSuccess();
    } catch (e: any) {
      toast.error(e?.message || "No se pudo enviar la transferencia");
    } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-bg/80 backdrop-blur-sm"
         data-testid="andes-transfer-modal">
      <div className="prosper-card p-5 max-w-md w-full mx-4 space-y-3">
        <div className="flex items-center gap-2">
          <Send size={16} className="text-primary"/>
          <h3 className="font-display font-bold text-fg text-base">
            Transferir entre wallets
          </h3>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">Asset</label>
            <select className="prosper-input mt-1 w-full text-xs"
                    data-testid="andes-transfer-asset"
                    value={asset} onChange={e => setAsset(e.target.value as any)}>
              <option value="arsa">ARSa</option>
              <option value="usdc">USDC</option>
              <option value="usdt">USDT</option>
            </select>
          </div>
          <div>
            <label className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">Red</label>
            <select className="prosper-input mt-1 w-full text-xs"
                    data-testid="andes-transfer-chain"
                    value={chain} onChange={e => setChain(e.target.value as any)}>
              <option value="stellar">Stellar</option>
              <option value="base">Base</option>
            </select>
          </div>
        </div>
        <div>
          <label className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">Monto</label>
          <input className="prosper-input mt-1 w-full text-xs"
                  data-testid="andes-transfer-amount"
                  value={amount} onChange={e => setAmount(e.target.value)}/>
        </div>
        <div>
          <label className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">Dirección destino</label>
          <input className="prosper-input mt-1 w-full text-xs font-mono"
                  data-testid="andes-transfer-to-address"
                  placeholder={chain === "stellar" ? "G…" : "0x…"}
                  value={toAddress} onChange={e => setToAddr(e.target.value)}/>
        </div>
        {chain === "stellar" && (
          <div>
            <label className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">Memo (opcional)</label>
            <input className="prosper-input mt-1 w-full text-xs"
                    value={memo} onChange={e => setMemo(e.target.value)}/>
          </div>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose}
                  className="prosper-btn-ghost h-9 text-xs">Cancelar</button>
          <button onClick={submit}
                  disabled={busy || !amount || !toAddress}
                  data-testid="andes-transfer-submit"
                  className="prosper-btn-primary h-9 text-xs gap-1.5">
            <ArrowRight size={11}/> Enviar transferencia
          </button>
        </div>
      </div>
    </div>
  );
}

