"use client";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  ArrowDownToLine, ArrowUpFromLine, Banknote, Check, Copy,
  Loader2, X, AlertTriangle, ListOrdered, ArrowDownLeft, ArrowUpRight,
} from "lucide-react";
import { toast } from "sonner";
import {
  cvuLookup, submitWithdraw, useRampMovements,
  fmtArsa, shortCvu,
  type CvuLookup, type RampMovement, type TxStatus,
} from "@/lib/ramp";

/** Phase 15.1 — Deposit instructions modal.
 *
 * Andes is deposit-driven: there is no "create order" step. The user simply
 * transfers ARS to their CVU and the balance shows up automatically once the
 * `fiat.deposit.success` webhook arrives. We surface the CVU/alias prominently
 * with copy buttons + a 3-step "qué hacer" explainer.
 */
export function DepositInstructionsModal({
  open, onClose, cvu, alias, wallet,
}: {
  open: boolean; onClose: () => void;
  cvu: string | null; alias: string | null; wallet: string | null;
}) {
  const [copied, setCopied] = useState<string | null>(null);
  if (!open) return null;

  const copy = async (v: string | null, key: string, label: string) => {
    if (!v) return;
    try { await navigator.clipboard?.writeText(v); }
    catch { toast.error("No se pudo copiar"); return; }
    setCopied(key);
    toast.success(`${label} copiado`);
    setTimeout(() => setCopied(null), 1500);
  };

  return (
    <div className="fixed inset-0 bg-bg/70 backdrop-blur-sm z-50 grid place-items-center p-4"
         onClick={onClose}
         data-testid="deposit-modal">
      <div className="prosper-card p-6 max-w-lg w-full"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between mb-3">
          <div className="flex items-center gap-2">
            <ArrowDownToLine size={18} className="text-primary"/>
            <h2 className="font-display font-bold text-lg text-fg">
              Depositar ARSa
            </h2>
          </div>
          <button onClick={onClose} aria-label="Cerrar"
                  data-testid="deposit-modal-close"
                  className="text-fg-subtle hover:text-fg">
            <X size={16}/>
          </button>
        </div>

        <p className="text-xs text-fg-muted mb-5 leading-snug">
          Transferí <strong>ARS</strong> desde tu home banking al CVU o alias
          de abajo. En cuanto la red lo confirme, tu balance ARSa se actualiza
          automáticamente · <em>peso digital 1:1</em>.
        </p>

        <div className="space-y-3">
          <DepRow label="CVU" value={shortCvu(cvu)} raw={cvu}
                  testid="deposit-modal-cvu"
                  copied={copied === "cvu"}
                  onCopy={() => copy(cvu, "cvu", "CVU")}/>
          <DepRow label="Alias" value={alias || "—"} raw={alias}
                  testid="deposit-modal-alias"
                  copied={copied === "alias"}
                  onCopy={() => copy(alias, "alias", "Alias")}/>
          <DepRow label="Wallet ARSa (Stellar)"
                  value={wallet
                    ? wallet.slice(0, 10) + "…" + wallet.slice(-6)
                    : "—"}
                  raw={wallet}
                  small
                  testid="deposit-modal-wallet"
                  copied={copied === "wallet"}
                  onCopy={() => copy(wallet, "wallet", "Wallet")}/>
        </div>

        <ol className="mt-5 space-y-2 text-xs text-fg-muted list-decimal pl-4">
          <li>Copiá el CVU o alias y pegalo en tu home banking.</li>
          <li>Hacé la transferencia desde tu cuenta personal (mismo CUIT).</li>
          <li>En <strong>~1 minuto</strong> verás tus ARSa acreditados acá.</li>
        </ol>

        <div className="mt-5 flex justify-end">
          <button onClick={onClose}
                  data-testid="deposit-modal-ok"
                  className="prosper-btn-primary h-9 text-xs">
            Listo
          </button>
        </div>
      </div>
    </div>
  );
}

function DepRow({ label, value, raw, copied, onCopy, small, testid }: {
  label: string; value: string; raw: string | null;
  copied: boolean; onCopy: () => void; small?: boolean; testid?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3 px-3 py-2 rounded border border-border bg-surface">
      <div className="flex-1 min-w-0">
        <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
          {label}
        </div>
        <div className={`${small ? "text-[11px]" : "text-sm"} font-mono text-fg break-all`}
             data-testid={testid}>
          {value}
        </div>
      </div>
      <button onClick={onCopy} disabled={!raw}
              className="inline-flex items-center gap-1 text-[11px] font-mono uppercase text-fg-subtle hover:text-fg disabled:opacity-40">
        {copied ? <Check size={12} className="text-success"/> : <Copy size={12}/>}
        {copied ? "Copiado" : "Copiar"}
      </button>
    </div>
  );
}


/** Phase 15.1 — Withdraw form (offramp).
 *  Flow: monto + CVU/alias → lookup titular → confirmar → POST /withdraw. */
export function WithdrawModal({
  open, onClose, endCustomerId, currentBalance,
  onSubmitted,
}: {
  open: boolean; onClose: () => void; endCustomerId: string;
  currentBalance: string;
  onSubmitted: (mv: RampMovement) => void;
}) {
  const [amount, setAmount] = useState("");
  const [destKind, setDestKind] = useState<"cvu" | "alias">("cvu");
  const [dest, setDest] = useState("");
  const [looking, setLooking] = useState(false);
  const [holder, setHolder] = useState<CvuLookup | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [lookupError, setLookupError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setAmount(""); setDest(""); setHolder(null);
      setSubmitting(false); setLookupError(null);
    }
  }, [open]);

  if (!open) return null;

  const amountNum = parseFloat(amount.replace(/[.,]/g, c => c === "," ? "." : ""));
  const insufficient = !Number.isNaN(amountNum) && amountNum > parseFloat(currentBalance);
  const canLookup = dest.trim().length >= 6 && !looking && !holder;
  const canSubmit = Number.isFinite(amountNum) && amountNum > 0 && holder && !insufficient && !submitting;

  const doLookup = async () => {
    setLooking(true);
    setLookupError(null);
    try {
      const r = await cvuLookup(destKind === "cvu"
        ? { cvu: dest.trim() }
        : { alias: dest.trim() });
      if (!r.holder_name) {
        setLookupError("No pudimos resolver el titular para ese destino.");
        return;
      }
      setHolder(r);
    } catch (e: any) {
      setLookupError(e?.message || "Error consultando el destino");
    } finally { setLooking(false); }
  };

  const doSubmit = async () => {
    if (!holder) return;
    setSubmitting(true);
    try {
      const idem = "wd-" + Math.random().toString(36).slice(2, 10) + "-" + Date.now();
      const mv = await submitWithdraw(
        endCustomerId,
        {
          amount: amountNum.toString(),
          to_cvu:   destKind === "cvu"   ? dest.trim() : undefined,
          to_alias: destKind === "alias" ? dest.trim() : undefined,
          holder_name_confirmed: holder.holder_name || undefined,
        },
        idem,
      );
      toast.success(`Retiro enviado por ${fmtArsa(amountNum)}`);
      onSubmitted(mv);
      onClose();
    } catch (e: unknown) {
      const msg = (e instanceof Error && e.message)
        ? e.message
        : (typeof e === "string" ? e : "No se pudo enviar el retiro");
      toast.error(msg);
    } finally { setSubmitting(false); }
  };

  return (
    <div className="fixed inset-0 bg-bg/70 backdrop-blur-sm z-50 grid place-items-center p-4"
         onClick={onClose}
         data-testid="withdraw-modal">
      <div className="prosper-card p-6 max-w-md w-full"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between mb-3">
          <div className="flex items-center gap-2">
            <ArrowUpFromLine size={18} className="text-primary"/>
            <h2 className="font-display font-bold text-lg text-fg">
              Retirar ARSa
            </h2>
          </div>
          <button onClick={onClose} aria-label="Cerrar"
                  data-testid="withdraw-modal-close"
                  className="text-fg-subtle hover:text-fg">
            <X size={16}/>
          </button>
        </div>

        <div className="text-[11px] text-fg-muted mb-3">
          Saldo disponible: <span className="font-mono text-fg">{fmtArsa(currentBalance)}</span>
        </div>

        {/* Amount */}
        <label className="block mb-3">
          <span className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
            Monto en ARSa
          </span>
          <div className="relative mt-1">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-fg-muted text-sm">$</span>
            <input
              type="text"
              inputMode="decimal"
              value={amount}
              onChange={e => { setAmount(e.target.value); setHolder(null); }}
              placeholder="0,00"
              data-testid="withdraw-amount-input"
              className="w-full pl-7 pr-3 h-10 rounded border border-border bg-surface text-fg font-mono text-base focus:outline-none focus:border-primary"
            />
          </div>
          {insufficient && (
            <div className="text-[10px] text-danger mt-1"
                 data-testid="withdraw-insufficient">
              Saldo insuficiente
            </div>
          )}
        </label>

        {/* Destination kind tabs */}
        <div className="flex gap-1 mb-2 text-[11px] font-mono uppercase">
          {(["cvu", "alias"] as const).map(k => (
            <button
              key={k}
              data-testid={`withdraw-tab-${k}`}
              onClick={() => { setDestKind(k); setHolder(null); setDest(""); }}
              className={`px-2.5 py-1 rounded ${destKind === k
                ? "bg-primary text-white"
                : "bg-surface border border-border text-fg-muted hover:text-fg"}`}>
              {k}
            </button>
          ))}
        </div>

        {/* Destination input */}
        <label className="block mb-3">
          <span className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
            {destKind === "cvu" ? "CVU destino (22 dígitos)" : "Alias destino"}
          </span>
          <div className="flex gap-2 mt-1">
            <input
              type="text"
              value={dest}
              onChange={e => { setDest(e.target.value); setHolder(null); setLookupError(null); }}
              placeholder={destKind === "cvu" ? "0000003123…" : "mi.alias"}
              data-testid="withdraw-destination-input"
              className="flex-1 px-3 h-10 rounded border border-border bg-surface text-fg font-mono text-sm focus:outline-none focus:border-primary"
            />
            <button
              onClick={doLookup}
              disabled={!canLookup}
              data-testid="withdraw-lookup-btn"
              className="prosper-btn-ghost h-10 text-xs gap-1.5 disabled:opacity-40">
              {looking ? <Loader2 size={12} className="animate-spin"/> : <Banknote size={12}/>}
              Buscar titular
            </button>
          </div>
          {lookupError && (
            <div className="text-[10px] text-danger mt-1" data-testid="withdraw-lookup-error">
              {lookupError}
            </div>
          )}
        </label>

        {/* Confirm panel */}
        {holder && (
          <div className="mb-4 rounded border border-success/40 bg-success/5 p-3 text-xs"
               data-testid="withdraw-confirm-panel">
            <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-0.5">
              Confirmá el destinatario
            </div>
            <div className="font-display font-bold text-fg" data-testid="withdraw-holder-name">
              {holder.holder_name}
            </div>
            <div className="text-fg-muted font-mono text-[11px] mt-0.5">
              {holder.holder_tax_id ? `CUIT/CUIL ${holder.holder_tax_id}` : ""}
              {holder.bank ? ` · ${holder.bank}` : ""}
            </div>
          </div>
        )}

        <div className="flex justify-between items-center">
          <button onClick={onClose} className="prosper-btn-ghost h-9 text-xs">
            Cancelar
          </button>
          <button
            onClick={doSubmit}
            disabled={!canSubmit}
            data-testid="withdraw-submit-btn"
            className="prosper-btn-primary h-9 text-xs gap-1.5 disabled:opacity-40">
            {submitting && <Loader2 size={12} className="animate-spin"/>}
            Retirar {amount ? fmtArsa(amountNum) : ""}
          </button>
        </div>
      </div>
    </div>
  );
}


/** Phase 15.1 — Movements list (deposits + withdrawals in ARSa). */
const STATUS_TONE: Record<TxStatus, string> = {
  Success:          "text-success bg-success/10",
  Pending:          "text-warning bg-warning/10",
  TransferPending:  "text-warning bg-warning/10",
  Failed:           "text-danger  bg-danger/10",
};

export function MovementsCard({ endCustomerId }: { endCustomerId: string }) {
  const t = useTranslations("movements_card");
  const { data, isLoading } = useRampMovements(endCustomerId);
  const statusLabelMap: Record<TxStatus, string> = {
    Success:          t("status_success"),
    Pending:          t("status_pending"),
    TransferPending:  t("status_transfer_pending"),
    Failed:           t("status_failed"),
  };
  return (
    <section className="prosper-card p-5 mb-6" data-testid="ramp-movements-card">
      <div className="flex items-center justify-between mb-3">
        <div>
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
            {t("kicker")}
          </div>
          <h3 className="font-display font-bold text-lg text-fg flex items-center gap-1.5 mt-0.5">
            <ListOrdered size={14} className="text-primary"/> {t("title")}
          </h3>
        </div>
        <span className="text-[10px] font-mono text-fg-subtle">
          {t("count", { count: data?.length ?? 0 })}
        </span>
      </div>

      {isLoading && (
        <div className="py-6 text-center text-fg-subtle text-xs italic">
          {t("loading")}
        </div>
      )}
      {!isLoading && (data?.length ?? 0) === 0 && (
        <div className="py-8 text-center text-fg-subtle"
             data-testid="ramp-movements-empty">
          <AlertTriangle size={18} className="mx-auto mb-1 text-fg-subtle"/>
          <div className="text-xs">{t("empty")}</div>
        </div>
      )}
      {!isLoading && (data?.length ?? 0) > 0 && (
        <ul className="space-y-1.5">
          {data!.map(m => (
            <li key={m.id}
                data-testid={`ramp-movement-${m.id}`}
                className="flex items-center gap-3 py-2 border-b border-border/40 last:border-0">
              <div className={`h-8 w-8 rounded-full flex items-center justify-center shrink-0 ${
                m.kind === "deposit" ? "bg-success/10 text-success" : "bg-primary/10 text-primary"
              }`}>
                {m.kind === "deposit"
                  ? <ArrowDownLeft size={14}/>
                  : <ArrowUpRight size={14}/>}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm text-fg font-display font-semibold">
                    {m.kind === "deposit" ? t("deposit") : t("withdraw")}
                  </span>
                  <span className={`text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded ${STATUS_TONE[m.status] || ""}`}>
                    {statusLabelMap[m.status] || m.status}
                  </span>
                  {m.destination_name && (
                    <span className="text-[11px] text-fg-muted truncate">
                      → {m.destination_name}
                    </span>
                  )}
                </div>
                <div className="text-[10px] font-mono text-fg-subtle">
                  {new Date(m.created_at).toLocaleString()}
                  {m.fail_reason && <> · {m.fail_reason}</>}
                </div>
              </div>
              <div className={`text-sm font-mono tabular shrink-0 ${
                m.kind === "deposit" ? "text-success" : "text-fg"
              }`}>
                {m.kind === "deposit" ? "+" : "−"} {fmtArsa(m.amount)}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
