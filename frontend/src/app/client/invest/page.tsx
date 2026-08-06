"use client";
/**
 * CMS-aligned invest wizard (Feb 2026).
 *
 * The Prosper protocol fixes the catalog: 12-month staking, two
 * settlement modalities (`end` o `month`). Cliente elige:
 *   1. Modalidad de cobro (end | month)
 *   2. Monto a invertir en su asset (USDC en este screen — ARSa vive en
 *      /client/invertir-arsa que comparte la misma lógica)
 *
 * Sin productos inventados (Liquid/30d/90d/180d): el rate viene del
 * contrato, lo refleja /v1/client/products como `apr_bps` indicativo.
 *
 * P0 Feb-2026 — Andes outbound transfer:
 *   For ARSa we now offer "Invertir ahora" which triggers a real on-chain
 *   transfer from the user's Andes Stellar wallet to the org's Prosper
 *   Treasury wallet for the chosen modality. USDC keeps the manual flow
 *   (/client/cargar-usdc) because Andes does not custody USDC for retail
 *   yet. The transfer requires an explicit confirmation modal + checkbox.
 */
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, useMemo } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import {
  Coins, ArrowRight, AlertTriangle, Lock, Calendar,
  CalendarClock, Copy, ShieldCheck, X, Loader2,
} from "lucide-react";
import { PageHeader, Badge } from "@prosper/ui";
import { api, ApiError } from "@/lib/api";
import { useClientMe } from "@/lib/client-portal";
import { fmtCur } from "@/lib/alfred";
import { useProducts, useInvestBalances, fmtPct } from "@/lib/invest";
import { Product } from "@/lib/invest";

type Modality = "end" | "month";
type Asset    = "usdc" | "arsa";

export default function InvestPage() {
  const t  = useTranslations("invest_page");
  const tc = useTranslations("common");
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialAsset: Asset = searchParams.get("asset") === "arsa" ? "arsa" : "usdc";

  const { data: me } = useClientMe();
  const canOperate = me?.features?.can_operate ?? false;

  const { data: prodData, isLoading: loadingProducts } = useProducts();
  const { data: bal } = useInvestBalances();

  const [asset, setAsset]         = useState<Asset>(initialAsset);
  const [modality, setModality]   = useState<Modality>("end");
  const [amount, setAmount]       = useState<string>("");
  const [confirmOpen, setConfirmOpen] = useState(false);

  // Catalog filtered by the asset the client picked. We support both
  // assets in the same wizard now (ARSa native — no more bridge).
  const assetProducts = useMemo(
    () => (prodData?.items ?? []).filter(
      (p) => (p.asset ?? "usdc") === asset && p.status === "active"),
    [prodData?.items, asset],
  );

  const product = useMemo(
    () => assetProducts.find((p) => p.modality === modality),
    [assetProducts, modality],
  );

  const assetUnit = asset === "arsa" ? "ARSa" : "USDC";

  // Asset-aware available balance (CMS protocol — each asset in its own lane).
  const { data: summary } = useSWR<{ cash: { usdc: number; arsa: number;
                                              usdc_platform: number; usdc_stellar: number;
                                              arsa_cvu: number; arsa_stellar: number } }>(
    "/v1/client/dashboard-summary", (p: string) => api(p));
  const available = asset === "arsa"
    ? (summary?.cash.arsa ?? 0)
    : (bal?.available_usdc ?? 0);
  const numericAmount = Number(amount) || 0;

  const error = !product ? null
    : numericAmount <= 0           ? null
    : numericAmount > available    ? t("error_exceeds", { amount: fmtCur(available, assetUnit) })
    : numericAmount < product.min_amount ? t("error_min", { min: product.min_amount, asset: assetUnit })
    : numericAmount > product.max_amount ? t("error_max", { max: product.max_amount, asset: assetUnit })
    : null;

  const maturityDate = useMemo(() => {
    const term = product?.term_days ?? 365;
    return new Date(Date.now() + term * 86400_000).toISOString().slice(0, 10);
  }, [product]);

  // CMS protocol: el wizard es un PREVIEW/CALCULADORA. El staking se crea
  // cuando el cliente transfiere fondos a su wallet asignada y el poller
  // detecta el depósito.
  //
  // ARSa flow: ahora ofrecemos "Invertir ahora" → modal de confirmación →
  //            POST /v1/client/invest/onchain (Andes outbound transfer).
  // USDC flow: continúa con el flujo manual → /client/cargar-usdc.
  const depositRoute = asset === "arsa" ? "/client/onramp"
                                          : "/client/cargar-usdc";
  const canContinue = !!product && !error && numericAmount > 0;

  // Resolve destination wallet for ARSa flow (lazy via API)
  const { data: depositWallets } = useSWR<{ wallets: { modality: string; address: string }[] }>(
    asset === "arsa" && canContinue ? "/v1/client/deposit-wallets" : null,
    (p: string) => api(p));
  const destinationAddress = useMemo(() => {
    const w = (depositWallets?.wallets || []).find(
      (x) => x.modality === modality);
    return w?.address || "";
  }, [depositWallets, modality]);

  if (!canOperate) {
    return (
      <>
        <PageHeader breadcrumbs={[{ label: tc("home"), href: "/client" }, { label: t("breadcrumb") }]}
                     kicker={t("kicker_block")} title={t("breadcrumb")} />
        <div className="prosper-card p-10 text-center" data-testid="invest-blocked">
          <AlertTriangle size={24} className="mx-auto text-warning mb-2" />
          <p className="text-sm text-fg-muted">{t("blocked_msg")}</p>
          <Link href="/apply" className="prosper-btn-primary inline-flex h-10 px-5 mt-4 text-sm">
            {t("continue_onboarding")} <ArrowRight size={14} />
          </Link>
        </div>
      </>
    );
  }

  return (
    <div data-testid="invest-page">
      <PageHeader
        breadcrumbs={[{ label: tc("home"), href: "/client" }, { label: t("breadcrumb") }]}
        kicker={t("kicker_preview", { asset: assetUnit })}
        title={t("title_sim", { asset: assetUnit })}
        subtitle={t("subtitle")}
      />

      {/* Asset toggle (ARSa native vs USDC native — no bridge) */}
      <div className="flex items-center gap-2 mb-5" data-testid="asset-toggle">
        <span className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mr-2">
          {t("asset_label")}
        </span>
        {(["arsa", "usdc"] as Asset[]).map((a) => (
          <button
            key={a}
            type="button"
            onClick={() => setAsset(a)}
            data-testid={`asset-${a}`}
            className={`px-3 h-8 rounded-full text-[11px] font-mono uppercase tracking-wider transition
                        ${asset === a
                            ? "bg-primary text-white"
                            : "bg-surface-hover text-fg-muted hover:bg-surface-active"}`}
          >
            {a === "arsa" ? "ARSa" : "USDC"}
          </button>
        ))}
      </div>

      <PendingOnchainBanner />

      {/* Available balance card — only shows USDC balance (ARSa balance
          comes from /v1/ramp/balances and is shown in the ARSa flow card) */}
      {asset === "usdc" && (
      <div className="prosper-card p-5 mb-6 flex items-center gap-4" data-testid="balance-card">
        <div className="h-12 w-12 rounded-full bg-primary/10 text-primary flex items-center justify-center">
          <Coins size={20} />
        </div>
        <div className="flex-1">
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
            {t("balance_label")}
          </div>
          <div className="text-2xl font-display font-extrabold font-mono tabular-nums text-fg"
               data-testid="balance-available">
            {fmtCur(available, "USDC")}
          </div>
        </div>
        {bal?.address && (
          <div className="text-right hidden sm:block">
            <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
              {t("wallet_stellar")}
            </div>
            <code className="text-[11px] font-mono text-fg-muted">
              {bal.address.slice(0, 6)}…{bal.address.slice(-6)}
            </code>
          </div>
        )}
      </div>
      )}
      {asset === "arsa" && (
      <div className="prosper-card p-5 mb-6 border-warning/30 bg-warning/5" data-testid="arsa-note">
        <div className="text-[11px] text-fg-muted">
          <strong className="text-warning">{t("arsa_note_prefix")}</strong> {t("arsa_note_body")}{" "}
          <strong className="text-fg" data-testid="arsa-available">
            {fmtCur(available, "ARSa")}
          </strong>
        </div>
      </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* LEFT — modality picker + amount */}
        <div className="lg:col-span-3 space-y-5">
          <section>
            <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-2">
              {t("step1_modality")}
            </div>
            {loadingProducts ? (
              <div className="prosper-card p-8 animate-pulse h-32" />
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3"
                   data-testid="modality-grid">
                <ModalityCard
                  modality="end"
                  product={assetProducts.find((p) => p.modality === "end")}
                  active={modality === "end"}
                  onClick={() => setModality("end")}
                />
                <ModalityCard
                  modality="month"
                  product={assetProducts.find((p) => p.modality === "month")}
                  active={modality === "month"}
                  onClick={() => setModality("month")}
                />
              </div>
            )}
          </section>

          <section>
            <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-2">
              {t("step2_amount")}
            </div>
            <div className="relative">
              <input
                type="number"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder={product ? String(product.min_amount) : "100"}
                className="prosper-input w-full h-14 text-3xl font-display font-bold pr-20"
                data-testid="invest-amount"
              />
              <span className="absolute right-4 top-1/2 -translate-y-1/2 text-sm font-mono
                                uppercase tracking-wider text-fg-subtle">{assetUnit}</span>
            </div>
            <div className="flex items-center justify-between mt-1">
              <button
                onClick={() => setAmount(String(available))}
                className="text-[11px] font-mono uppercase tracking-wider text-primary hover:underline"
                data-testid="invest-max">
                {t("use_max", { amount: fmtCur(available, assetUnit) })}
              </button>
              {error && (
                <span className="text-[11px] text-danger" data-testid="invest-error">{error}</span>
              )}
            </div>
          </section>
        </div>

        {/* RIGHT — Preview */}
        <div className="lg:col-span-2">
          <div className="prosper-card p-5 sticky top-20" data-testid="preview-card">
            <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
              {t("summary_label")}
            </div>
            <h3 className="font-display font-bold text-lg text-fg mt-0.5 mb-3">{t("preview_title")}</h3>

            {!product ? (
              <p className="text-fg-subtle text-sm py-6 text-center">
                {t("select_modality_hint")}
              </p>
            ) : (
              <div className="space-y-3 text-sm">
                <Row label={t("row_asset")} value={assetUnit} />
                <Row label={t("row_modality")}
                  value={product.modality === "end"
                          ? t("modality_end_label")
                          : t("modality_month_label")} />
                <Row label={t("row_term")}
                  value={t("row_term_value", { months: product.term_months ?? 12 })} />
                <Row label={t("row_rate")} value={fmtPct(product.apr_bps)} success />
                <Row label={t("row_maturity")} value={maturityDate} mono />
                <div className="h-px bg-border my-3" />
                <Row label={t("row_you_invest")} value={`${numericAmount.toFixed(2)} ${assetUnit}`} muted />
                {numericAmount > 0 && product.modality === "end" && (
                  <Row
                    label={t("row_you_receive_end")}
                    value={fmtCur(
                      numericAmount * (1 + product.apr_bps / 10_000),
                      assetUnit)}
                    large success
                  />
                )}
                {numericAmount > 0 && product.modality === "month" && (
                  <>
                    <Row
                      label={t("row_monthly_interest")}
                      value={fmtCur(
                        numericAmount * (product.apr_bps / 10_000) / 12,
                        assetUnit)}
                      success
                    />
                    <Row
                      label={t("row_capital_maturity")}
                      value={fmtCur(numericAmount, assetUnit)}
                      large
                    />
                  </>
                )}

                {asset === "arsa" ? (
                  <button
                    type="button"
                    disabled={!canContinue || !destinationAddress}
                    onClick={() => setConfirmOpen(true)}
                    className={"prosper-btn-primary w-full h-12 mt-4 text-sm gap-2 "
                      + ((canContinue && destinationAddress)
                           ? "" : "opacity-40 pointer-events-none")}
                    data-testid="invest-now-arsa">
                    <ShieldCheck size={14}/> {t("invest_now_arsa")}
                  </button>
                ) : (
                  <Link
                    href={
                      product && !error && numericAmount > 0
                        ? `${depositRoute}?modality=${modality}&amount=${numericAmount}`
                        : depositRoute
                    }
                    className="prosper-btn-primary w-full h-12 mt-4 text-sm gap-2"
                    data-testid="invest-continue">
                    <ArrowRight size={14}/>
                    {available > 0 ? t("continue_to_deposit") : t("deposit_usdc_first")}
                  </Link>
                )}
                <p className="text-[11px] text-fg-subtle mt-2 text-center">
                  {asset === "arsa" ? t("footnote_arsa") : t("footnote_usdc")}
                </p>
              </div>
            )}
          </div>
        </div>
      </div>

      {asset === "arsa" && confirmOpen && product && (
        <InvestConfirmModal
          modality={modality}
          amount={numericAmount}
          destinationAddress={destinationAddress}
          aprBps={product.apr_bps}
          maturityDate={maturityDate}
          onClose={() => setConfirmOpen(false)}
          onSuccess={(res) => {
            setConfirmOpen(false);
            toast.success("Transferencia iniciada. Detectando depósito on-chain…",
                            { duration: 6000 });
            // Small delay so the toast is visible before nav
            setTimeout(() => router.push(
              `/client/investments?pending=${res.position_id}`), 400);
          }}
        />
      )}
    </div>
  );
}

function ModalityCard({ modality, product, active, onClick }:
  { modality: Modality; product?: Product;
    active: boolean; onClick: () => void }) {
  const t = useTranslations("invest_page");
  const title = modality === "end" ? t("modality_end_title") : t("modality_month_title");
  const subtitle = modality === "end" ? t("modality_end_desc") : t("modality_month_desc");
  const Icon = modality === "end" ? Lock : CalendarClock;
  const disabled = !product;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      data-testid={`modality-${modality}`}
      className={`p-4 rounded-xl border text-left transition-all
                  ${active ? "border-primary bg-primary/5 ring-1 ring-primary"
                            : "border-border hover:bg-surface-hover"}
                  ${disabled ? "opacity-40 cursor-not-allowed" : ""}`}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Icon size={14} className="text-primary" />
          <div className="text-sm font-display font-bold text-fg">{title}</div>
        </div>
        {product && (
          <Badge tone={modality === "end" ? "success" : "info"} size="sm">
            APR {fmtPct(product.apr_bps)}
          </Badge>
        )}
      </div>
      <div className="text-[11px] text-fg-muted line-clamp-2">{subtitle}</div>
      {product && (
        <div className="mt-3 flex items-center gap-3 text-[10px] font-mono text-fg-subtle">
          <span className="inline-flex items-center gap-1">
            <Calendar size={10} /> {t("term_12_months")}
          </span>
          <span className="inline-flex items-center gap-1">
            <Coins size={10} /> {t("min_amount", { amount: product.min_amount })}
          </span>
        </div>
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Confirmation modal — explicit authorization for ARSa on-chain transfer.
// Per Feb-2026 spec: shows the FULL destination address (not truncated),
// the amount, modality, maturity, and a mandatory checkbox the user must
// tick before the "Autorizar transferencia" button becomes clickable.
// ---------------------------------------------------------------------------
type ConfirmResp = {
  ok: boolean;
  position_id: string;
  andes_transfer_id: string;
  tx_hash: string | null;
  status: string;
  destination: string;
  message?: string;
  skipped?: boolean;
};

function InvestConfirmModal({
  modality, amount, destinationAddress, aprBps, maturityDate,
  onClose, onSuccess,
}: {
  modality: Modality;
  amount: number;
  destinationAddress: string;
  aprBps: number;
  maturityDate: string;
  onClose: () => void;
  onSuccess: (res: ConfirmResp) => void;
}) {
  const t = useTranslations("invest_page");
  const [agreed, setAgreed]   = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);

  const onConfirm = async () => {
    if (!agreed || loading) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api<ConfirmResp>("/v1/client/invest/onchain", {
        method: "POST",
        body: JSON.stringify({
          asset:                  "arsa",
          modality,
          amount,
          authorized:             true,
          confirmed_destination:  destinationAddress,
          confirmed_amount:       amount,
        }),
      });
      onSuccess(res);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message
                  : e instanceof Error ? e.message
                  : "Error";
      setError(msg);
      toast.error(msg);
      setLoading(false);
    }
  };

  return (
    <div
      data-testid="invest-confirm-modal"
      className="fixed inset-0 z-50 flex items-center justify-center
                  bg-black/60 backdrop-blur-sm p-4"
      onClick={() => !loading && onClose()}
    >
      <div
        className="prosper-card max-w-lg w-full p-6 relative"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          onClick={() => !loading && onClose()}
          disabled={loading}
          className="absolute top-3 right-3 p-1 rounded-full
                      hover:bg-surface-hover transition disabled:opacity-30"
          data-testid="invest-confirm-close"
          aria-label={t("confirm_close")}
        >
          <X size={16} className="text-fg-muted" />
        </button>

        <div className="flex items-center gap-2 mb-3">
          <div className="h-10 w-10 rounded-full bg-warning/10 text-warning
                            flex items-center justify-center">
            <AlertTriangle size={18} />
          </div>
          <div>
            <h2 className="font-display font-bold text-lg text-fg">
              {t("confirm_modal_title")}
            </h2>
            <p className="text-[11px] text-fg-subtle">
              {t("confirm_modal_sub")}
            </p>
          </div>
        </div>

        <div className="space-y-2 text-sm bg-surface-hover/40 rounded-lg p-4
                          border border-border">
          <Row label={t("confirm_amount")} value={`${amount.toLocaleString(undefined)} ARSa`} large success />
          <Row label={t("confirm_modality")}
                value={modality === "end" ? t("modality_end_label") : t("modality_month_label")} />
          <Row label={t("confirm_rate_annual")} value={`${(aprBps / 100).toFixed(2)}%`} success />
          <Row label={t("confirm_maturity")} value={maturityDate} mono />

          <div className="pt-2 border-t border-border mt-2">
            <div className="text-[10px] font-mono uppercase tracking-wider
                              text-fg-subtle mb-1">
              {t("confirm_dest_label", { modality })}
            </div>
            <div className="flex items-start gap-2">
              <code className="text-[11px] font-mono break-all text-fg flex-1"
                     data-testid="invest-confirm-destination">
                {destinationAddress || "—"}
              </code>
              <button
                type="button"
                onClick={() => {
                  navigator.clipboard.writeText(destinationAddress);
                  toast.success(t("confirm_copy_toast"));
                }}
                className="p-1 rounded-md hover:bg-surface-hover transition"
                aria-label={t("confirm_copy_aria")}
              >
                <Copy size={12} className="text-fg-muted" />
              </button>
            </div>
          </div>
        </div>

        <label
          className="flex items-start gap-2 mt-4 cursor-pointer select-none
                      p-3 rounded-lg border border-border
                      hover:bg-surface-hover transition"
          data-testid="invest-confirm-checkbox-label"
        >
          <input
            type="checkbox"
            checked={agreed}
            onChange={(e) => setAgreed(e.target.checked)}
            disabled={loading}
            className="mt-0.5"
            data-testid="invest-confirm-checkbox"
          />
          <span className="text-[12px] text-fg-muted leading-snug">
            {t("confirm_checkbox_prefix")}{" "}
            <strong className="text-fg">{amount.toLocaleString(undefined)} ARSa</strong>{" "}
            {t("confirm_checkbox_suffix")}
          </span>
        </label>

        {error && (
          <div className="text-[11px] text-danger mt-3 p-2 rounded
                            bg-danger/5 border border-danger/20"
                 data-testid="invest-confirm-error">
            {error}
          </div>
        )}

        <div className="flex gap-2 mt-4">
          <button
            type="button"
            onClick={onClose}
            disabled={loading}
            className="prosper-btn-secondary h-11 px-5 text-sm flex-1"
            data-testid="invest-confirm-cancel"
          >
            {t("confirm_cancel")}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={!agreed || loading || !destinationAddress}
            className={"prosper-btn-primary h-11 px-5 text-sm flex-1 gap-2 "
              + ((!agreed || loading || !destinationAddress)
                  ? "opacity-40 pointer-events-none" : "")}
            data-testid="invest-confirm-authorize"
          >
            {loading
              ? <><Loader2 size={14} className="animate-spin" /> {t("confirm_processing")}</>
              : <><ShieldCheck size={14}/> {t("confirm_authorize")}</>}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pending-onchain banner — polls /client/positions every 30s while there
// is at least one pending placeholder, so users see the transition to
// `active` automatically once the staking poller picks the deposit up.
// ---------------------------------------------------------------------------
function PendingOnchainBanner() {
  const t = useTranslations("invest_page");
  const { data } = useSWR<{ items: { position_id: string; status: string;
                                       asset: string; modality: string;
                                       principal_native: number;
                                       andes_transfer_id?: string;
                                       created_at: string }[] }>(
    "/v1/client/positions",
    (p: string) => api(p),
    { refreshInterval: 30_000 });

  const pendings = (data?.items || []).filter(
    (p) => p.status === "pending_onchain");
  if (!pendings.length) return null;

  return (
    <div
      className="prosper-card p-4 mb-6 flex items-start gap-3
                  border-primary/30 bg-primary/5"
      data-testid="invest-pending-banner"
    >
      <Loader2 size={18} className="animate-spin text-primary mt-0.5" />
      <div className="flex-1 text-[12px] text-fg-muted">
        <div className="font-display font-bold text-sm text-fg mb-1">
          {t("pending_title")}
        </div>
        {pendings.length === 1
          ? t("pending_count_one", { count: pendings.length })
          : t("pending_count_other", { count: pendings.length })}
        <ul className="mt-2 space-y-1">
          {pendings.map((p) => (
            <li key={p.position_id} className="font-mono text-[11px]"
                 data-testid={`pending-row-${p.position_id}`}>
              · {p.principal_native.toLocaleString(undefined)} {p.asset.toUpperCase()}{" "}
              · {t("pending_modality_label")} {p.modality}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function Row({ label, value, muted, success, small, large, mono }:
  { label: string; value: string; muted?: boolean; success?: boolean;
    small?: boolean; large?: boolean; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className={`${small ? "text-xs" : "text-sm"} text-fg-muted`}>{label}</span>
      <span className={`${mono || small ? "font-mono" : ""}
                       ${small ? "text-xs" : large ? "text-2xl font-display font-extrabold" : "text-sm"}
                       ${success ? "text-success" : muted ? "text-fg-muted" : "text-fg"}
                       tabular-nums`}>
        {value}
      </span>
    </div>
  );
}