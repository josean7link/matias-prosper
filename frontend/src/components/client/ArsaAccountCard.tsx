"use client";
import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  ArrowDownToLine, ArrowUpFromLine, Copy, Sparkles, Info,
  RefreshCw, AlertTriangle, TrendingUp,
} from "lucide-react";
import { toast } from "sonner";
import {
  useRampAccounts, useRampBalances,
  fmtArsa, shortCvu, isWalletActivating,
  chainLabel, type RampAccount,
} from "@/lib/ramp";
import {
  DepositInstructionsModal, WithdrawModal,
} from "@/components/client/RampMovementsAndForms";

/** Phase 14 — Client portal ARSa card. */
export function ArsaAccountCard({ orgId }: { orgId: string }) {
  const t = useTranslations("arsa_card");
  const { data: accounts } = useRampAccounts();
  const [copied, setCopied] = useState<string | null>(null);

  const acc: RampAccount | undefined = (accounts ?? [])
    .find(a => a.end_customer_id === orgId) ?? (accounts ?? [])[0];

  if (!acc) {
    return (
      <div
        data-testid="arsa-card-empty"
        className="rounded-2xl border border-border bg-surface p-5 mb-6 text-sm">
        <div className="flex items-start gap-3">
          <div className="h-9 w-9 rounded-full bg-fg/5 flex items-center justify-center shrink-0">
            <AlertTriangle size={16} className="text-warning"/>
          </div>
          <div>
            <div className="font-display font-bold text-fg text-sm">
              {t("empty_title")}
            </div>
            <p className="text-fg-muted text-xs mt-1 max-w-md">
              {t("empty_msg")}
            </p>
          </div>
        </div>
      </div>
    );
  }

  return <ArsaCardInner acc={acc} copied={copied} setCopied={setCopied}/>;
}

function ArsaCardInner({ acc, copied, setCopied }: {
  acc: RampAccount;
  copied: string | null;
  setCopied: (v: string | null) => void;
}) {
  const t = useTranslations("arsa_card");
  const { data: bal, isLoading, mutate } = useRampBalances(acc.end_customer_id);
  // Phase 17: balances may have multiple ARSa rows (one per chain). Pick the
  // primary (largest balance) for the hero number; render the others below as
  // separate, never-summed rows.
  const arsaRows = (bal?.items ?? []).filter(b => b.asset_code === "arsa");
  const primary  = arsaRows.slice().sort((a, b) =>
    parseFloat(b.amount) - parseFloat(a.amount))[0] ?? arsaRows[0];
  const amount   = primary?.amount ?? "0";
  // Prefer the wallet's actual chain (truth) over the balance row chain.
  const primaryChain = acc.wallet_chain ?? primary?.chain ?? "stellar";
  const secondaryRows = arsaRows.filter(r =>
    r !== primary && r.chain !== primaryChain);

  const isPending     = acc.onboarding_status !== "approved" || !acc.cvu;
  const isActivating  = isWalletActivating(acc);     // Phase 18 — Stellar pending
  const deposit_disabled  = isPending || isActivating;
  const withdraw_disabled = isPending || isActivating || parseFloat(amount) <= 0;
  const [depositOpen, setDepositOpen] = useState(false);
  const [withdrawOpen, setWithdrawOpen] = useState(false);

  const copy = async (v: string | null, key: string, label: string) => {
    if (!v) return;
    try {
      await navigator.clipboard?.writeText(v);
      setCopied(key);
      toast.success(t("copy_success", { label }));
      setTimeout(() => setCopied(null), 1500);
    } catch { toast.error(t("copy_error")); }
  };

  return (
    <section
      data-testid="arsa-account-card"
      className="relative overflow-hidden rounded-2xl mb-6 p-6 text-white
                 bg-gradient-to-br from-[#0b3aa3] via-[#1e4ed8] to-[#3563f4]
                 shadow-[0_8px_32px_-12px_rgba(11,58,163,0.45)]"
    >
      {/* Decorative pattern */}
      <div aria-hidden
        className="absolute -right-12 -top-12 h-48 w-48 rounded-full bg-white/8 blur-3xl"/>
      <div aria-hidden
        className="absolute -left-6 -bottom-10 h-40 w-40 rounded-full bg-white/5 blur-3xl"/>

      <div className="relative grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* LEFT — Balance */}
        <div className="lg:col-span-3">
          <div className="flex items-center gap-2 text-[10px] font-mono uppercase tracking-[0.22em] text-white/70">
            <Sparkles size={11}/> {t("eyebrow")}
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span
              data-testid="arsa-balance"
              className="font-display font-bold text-5xl lg:text-6xl tracking-tight"
            >
              {fmtArsa(amount)}
            </span>
            <span className="text-sm font-mono tracking-wider text-white/80">
              ARSa
            </span>
          </div>
          <div className="mt-1.5 flex items-center gap-2 flex-wrap">
            <p className="text-xs text-white/70 flex items-center gap-1.5">
              <Info size={11}/> {t("subline")}
            </p>
            {primaryChain && (
              <span
                data-testid="arsa-chain-badge"
                className="inline-flex items-center gap-1 text-[10px] font-mono uppercase tracking-wider
                            px-2 py-0.5 rounded-full bg-white/15 text-white/85 border border-white/10">
                {t("chain_label", { chain: chainLabel(primaryChain) })}
              </span>
            )}
          </div>

          <button
            onClick={() => mutate()}
            disabled={isLoading}
            data-testid="arsa-refresh"
            className="mt-4 inline-flex items-center gap-1.5 text-[11px] font-mono uppercase tracking-wider
                       text-white/80 hover:text-white transition-colors">
            <RefreshCw size={11} className={isLoading ? "animate-spin" : ""}/>
            {isLoading ? t("refreshing") : t("refresh")}
          </button>

          <div className="mt-6 flex flex-wrap gap-2">
            <ActionPill
              testid="arsa-deposit-btn"
              icon={<ArrowDownToLine size={13}/>}
              label={t("deposit")}
              subtitle={t("deposit_subtitle")}
              disabled={deposit_disabled}
              tooltip={isActivating
                ? t("tooltip_activating_deposit")
                : (isPending ? t("tooltip_pending_cvu") : undefined)}
              href={deposit_disabled ? undefined : "/client/onramp"}
            />
            <ActionPill
              testid="arsa-withdraw-btn"
              icon={<ArrowUpFromLine size={13}/>}
              label={t("withdraw")}
              subtitle={t("withdraw_subtitle")}
              disabled={withdraw_disabled}
              tooltip={isActivating
                ? t("tooltip_activating_withdraw")
                : (isPending
                    ? t("tooltip_pending_cvu")
                    : (parseFloat(amount) <= 0
                        ? t("tooltip_insufficient")
                        : undefined))}
              href={withdraw_disabled ? undefined : "/client/offramp"}
            />
            <a href="/client/invest?asset=arsa"
                data-testid="arsa-invest-btn"
                className="inline-flex items-center gap-2 rounded-full bg-white text-primary
                           h-9 px-3 text-[11px] font-mono uppercase tracking-wider
                           hover:bg-white/90 transition-colors shadow-sm">
              <TrendingUp size={13}/>
              <span className="flex flex-col items-start leading-tight">
                <span className="font-display font-bold normal-case tracking-normal text-[12px]">
                  {t("invest_label")}
                </span>
                <span className="text-[9px] opacity-70 normal-case tracking-normal">
                  {t("invest_subtitle")}
                </span>
              </span>
            </a>
          </div>

          {isActivating && (
            <div
              data-testid="arsa-activating-banner"
              className="mt-4 rounded-lg bg-white/10 border border-white/15 text-[11px] leading-snug px-3 py-2 text-white/95 flex items-start gap-2">
              <RefreshCw size={12} className="animate-spin shrink-0 mt-0.5"/>
              <div>
                <strong>{t("activating_title")}</strong>
                {" "}{t("activating_msg")}
                {acc.cvu ? t("activating_with_cvu") : ""}
              </div>
            </div>
          )}

          {!isActivating && isPending && acc.onboarding_message && (
            <div
              data-testid="arsa-pending-banner"
              className="mt-4 rounded-lg bg-white/10 text-[11px] leading-snug px-3 py-2 text-white/90">
              {acc.onboarding_message}
            </div>
          )}

          {secondaryRows.length > 0 && (
            <div className="mt-4 rounded-lg bg-white/5 border border-white/10 px-3 py-2 space-y-1"
                 data-testid="arsa-multichain-secondary">
              <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-white/55">
                {t("secondary_chain_title")}
              </div>
              {secondaryRows.map(r => (
                <div key={`${r.asset_code}-${r.chain}`}
                     className="flex items-center justify-between text-[11px]"
                     data-testid={`arsa-secondary-row-${r.chain}`}>
                  <span className="font-mono uppercase tracking-wider text-white/70">
                    {t("secondary_chain_row", {
                      chain: r.chain === "stellar" ? "Stellar"
                           : r.chain === "base"    ? "Base"
                           : r.chain,
                    })}
                  </span>
                  <span className="font-mono tabular text-white/90">
                    {fmtArsa(r.amount)} ARSa
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* RIGHT — CVU + Alias */}
        <div className="lg:col-span-2 lg:border-l lg:border-white/15 lg:pl-6 space-y-3">
          <KvLite
            label={t("kv_cvu")}
            value={shortCvu(acc.cvu)}
            raw={acc.cvu}
            testid="arsa-cvu"
            copied={copied === "cvu"}
            onCopy={() => copy(acc.cvu, "cvu", t("copy_label_cvu"))}
            pending={!acc.cvu}
            pendingLabel={t("pending_value")}
          />
          <KvLite
            label={t("kv_alias")}
            value={acc.alias || "—"}
            raw={acc.alias}
            testid="arsa-alias"
            copied={copied === "alias"}
            onCopy={() => copy(acc.alias, "alias", t("copy_label_alias"))}
            pending={!acc.alias}
            pendingLabel={t("pending_value")}
          />
          <KvLite
            label={t("kv_wallet", { chain: chainLabel(primaryChain) })}
            value={acc.wallet_address
              ? acc.wallet_address.slice(0, 8) + "…" + acc.wallet_address.slice(-6)
              : "—"}
            raw={acc.wallet_address}
            testid="arsa-wallet-address"
            copied={copied === "wallet"}
            onCopy={() => copy(acc.wallet_address, "wallet", t("copy_label_wallet"))}
            pending={!acc.wallet_address}
            pendingLabel={t("pending_value")}
            small
          />
        </div>
      </div>

      <DepositInstructionsModal
        open={depositOpen}
        onClose={() => setDepositOpen(false)}
        cvu={acc.cvu}
        alias={acc.alias}
        wallet={acc.wallet_address}
      />
      <WithdrawModal
        open={withdrawOpen}
        onClose={() => setWithdrawOpen(false)}
        endCustomerId={acc.end_customer_id}
        currentBalance={amount}
        onSubmitted={() => mutate()}
      />
    </section>
  );
}

function ActionPill({ icon, label, subtitle, disabled, tooltip, testid,
                       onClick, href }: {
  icon: React.ReactNode; label: string; subtitle: string;
  disabled?: boolean; tooltip?: string; testid: string;
  onClick?: () => void;
  href?: string;
}) {
  const base = `group inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm
                font-display font-semibold transition-all`;
  if (disabled) {
    return (
      <span
        title={tooltip}
        data-testid={testid}
        data-disabled="true"
        className={`${base} bg-white/10 text-white/60 cursor-not-allowed border border-white/10`}>
        {icon} <span>{label}</span>
        {tooltip && (
          <span className="text-[10px] font-mono uppercase tracking-wider text-white/50 ml-1">
            {tooltip}
          </span>
        )}
      </span>
    );
  }
  const inner = (
    <>
      {icon} <span>{label}</span>
      <span className="hidden sm:inline text-[10px] font-mono uppercase tracking-wider text-[#0b3aa3]/60 ml-1">
        {subtitle}
      </span>
    </>
  );
  const cls = `${base} bg-white text-[#0b3aa3] hover:bg-white/90 shadow-sm`;
  if (href) {
    return (
      <a href={href} data-testid={testid} className={cls}>{inner}</a>
    );
  }
  return (
    <button onClick={onClick} data-testid={testid} className={cls}>{inner}</button>
  );
}

function KvLite({
  label, value, raw, testid, onCopy, copied, pending, small, pendingLabel,
}: {
  label: string; value: string; raw: string | null | undefined;
  testid: string; onCopy: () => void; copied: boolean;
  pending?: boolean; small?: boolean; pendingLabel?: string;
}) {
  return (
    <div className="space-y-0.5">
      <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-white/55">
        {label}
      </div>
      <div className="flex items-center gap-2">
        <span
          data-testid={testid}
          className={`font-mono ${small ? "text-xs" : "text-sm"} ${pending ? "text-white/45 italic" : "text-white"} break-all`}>
          {pending ? (pendingLabel || "pending") : value}
        </span>
        {raw && !pending && (
          <button
            onClick={onCopy}
            aria-label={`Copy ${label}`}
            data-testid={`${testid}-copy`}
            className="text-white/60 hover:text-white transition-colors">
            <Copy size={12}/>
            {copied && (
              <span className="text-[9px] font-mono ml-1 align-middle">✓</span>
            )}
          </button>
        )}
      </div>
    </div>
  );
}
