"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useMemo } from "react";
import { toast } from "sonner";
import {
  Sparkles, Coins, Clock, ArrowRight, AlertTriangle, Zap,
  Lock, Calendar, TrendingUp,
} from "lucide-react";
import { PageHeader, Badge } from "@prosper/ui";
import { api } from "@/lib/api";
import { useClientMe } from "@/lib/client-portal";
import { fmtCur } from "@/lib/alfred";
import {
  useProducts, useInvestBalances, fmtPct,
  type Product,
} from "@/lib/invest";

const TONE: Record<string, "info" | "success" | "warning" | "default"> = {
  liquid_v1: "success",
  term_30:   "info",
  term_90:   "warning",
  term_180:  "default",
};

export default function InvestPage() {
  const router = useRouter();
  const { data: me } = useClientMe();
  const canOperate = me?.features?.can_operate ?? false;

  const { data: prodData, isLoading: loadingProducts } = useProducts();
  const { data: bal, mutate: mutBal } = useInvestBalances();
  const products = prodData?.items || [];

  const [pickedId, setPickedId] = useState<string>("liquid_v1");
  const [amount, setAmount]   = useState<string>("");
  const [confirming, setConfirming] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  const product = useMemo(
    () => products.find((p) => p.product_id === pickedId),
    [products, pickedId],
  );

  const available = bal?.available_usdc ?? 0;
  const numericAmount = Number(amount) || 0;

  const error = !product ? null
    : numericAmount <= 0           ? null
    : numericAmount > available    ? `Excede tu saldo libre (${fmtCur(available, "USDC")})`
    : numericAmount < product.min_amount ? `Mínimo: ${product.min_amount} USDC`
    : numericAmount > product.max_amount ? `Máximo: ${product.max_amount} USDC`
    : null;

  const maturityDate = product && product.term_days > 0
    ? new Date(Date.now() + product.term_days * 86400_000)
        .toISOString().slice(0, 10)
    : null;

  const submit = async () => {
    if (!product || error || numericAmount <= 0) return;
    setConfirming(true);
    try {
      const res = await api<{ ok: boolean; position: { position_id: string } }>(
        "/v1/client/positions",
        { method: "POST", body: JSON.stringify({
            product_id: product.product_id,
            amount_usdc: numericAmount,
          }) }
      );
      toast.success("Compra confirmada — posición creada");
      mutBal();
      router.push(`/client/investments/${res.position.position_id}`);
    } catch (err) {
      const e = err as Error;
      toast.error(e.message || "Error al ejecutar la compra");
    } finally {
      setConfirming(false);
      setShowConfirm(false);
    }
  };

  if (!canOperate) {
    return (
      <>
        <PageHeader breadcrumbs={[{ label: "Client", href: "/client" }, { label: "Invertir" }]}
                     kicker="Phase 9 · Manual buy" title="Invertir" />
        <div className="prosper-card p-10 text-center" data-testid="invest-blocked">
          <AlertTriangle size={24} className="mx-auto text-warning mb-2" />
          <p className="text-sm text-fg-muted">Tu KYB no está aprobado todavía.</p>
          <Link href="/apply" className="prosper-btn-primary inline-flex h-10 px-5 mt-4 text-sm">
            Continuar onboarding <ArrowRight size={14} />
          </Link>
        </div>
      </>
    );
  }

  return (
    <div data-testid="invest-page">
      <PageHeader
        breadcrumbs={[{ label: "Client", href: "/client" }, { label: "Invertir" }]}
        kicker="Phase 9 · Comprar Prosper"
        title="Invertir USDC en Prosper"
        subtitle="Convertí tu USDC libre en posiciones que generan APR diariamente."
      />

      {/* Available balance card */}
      <div className="prosper-card p-5 mb-6 flex items-center gap-4" data-testid="balance-card">
        <div className="h-12 w-12 rounded-full bg-primary/10 text-primary flex items-center justify-center">
          <Coins size={20} />
        </div>
        <div className="flex-1">
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
            Saldo USDC disponible
          </div>
          <div className="text-2xl font-display font-extrabold font-mono tabular-nums text-fg"
               data-testid="balance-available">
            {fmtCur(available, "USDC")}
          </div>
        </div>
        {bal?.address && (
          <div className="text-right hidden sm:block">
            <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
              Wallet Stellar
            </div>
            <code className="text-[11px] font-mono text-fg-muted">
              {bal.address.slice(0, 6)}…{bal.address.slice(-6)}
            </code>
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* LEFT — product cards + amount */}
        <div className="lg:col-span-3 space-y-5">
          <section>
            <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-2">
              1. Producto
            </div>
            {loadingProducts ? (
              <div className="prosper-card p-8 animate-pulse h-32" />
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3" data-testid="product-grid">
                {products.map((p) => (
                  <ProductCard
                    key={p.product_id}
                    product={p}
                    active={pickedId === p.product_id}
                    onClick={() => setPickedId(p.product_id)}
                  />
                ))}
              </div>
            )}
          </section>

          <section>
            <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-2">
              2. Monto a invertir
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
                                uppercase tracking-wider text-fg-subtle">USDC</span>
            </div>
            <div className="flex items-center justify-between mt-1">
              <button
                onClick={() => setAmount(String(available))}
                className="text-[11px] font-mono uppercase tracking-wider text-primary hover:underline"
                data-testid="invest-max">
                Usar máximo · {fmtCur(available, "USDC")}
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
              Resumen
            </div>
            <h3 className="font-display font-bold text-lg text-fg mt-0.5 mb-3">Preview</h3>

            {!product ? (
              <p className="text-fg-subtle text-sm py-6 text-center">Seleccioná un producto</p>
            ) : (
              <div className="space-y-3 text-sm">
                <Row label="Producto" value={product.name} />
                <Row label="APR" value={fmtPct(product.apr_bps)} success />
                {product.term_days > 0 ? (
                  <Row label="Lock" value={`${product.term_days} días`} />
                ) : (
                  <Row label="Lock" value="Sin lock · redimí cuando quieras" />
                )}
                {maturityDate && (
                  <Row label="Maturity" value={maturityDate} mono />
                )}
                <div className="h-px bg-border my-3" />
                <Row label="Invertís" value={`${numericAmount.toFixed(2)} USDC`} muted />
                <Row label="Recibís"
                     value={`${numericAmount.toFixed(2)} PROS`} success large />
                {numericAmount > 0 && (
                  <Row
                    label={product.term_days > 0 ? `Yield al madurar` : "Yield anual estimado"}
                    value={fmtCur(
                      numericAmount * (product.apr_bps / 10_000)
                        * (product.term_days > 0 ? product.term_days / 365 : 1),
                      "USDC",
                    )}
                    small success
                  />
                )}

                <button
                  onClick={() => setShowConfirm(true)}
                  disabled={!!error || numericAmount <= 0 || confirming}
                  className="prosper-btn-primary w-full h-12 mt-4 text-sm gap-2 disabled:opacity-40"
                  data-testid="invest-confirm">
                  {confirming ? "Comprando…" : (<><Zap size={14}/> Confirmar inversión</>)}
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Confirm modal */}
      {showConfirm && product && (
        <ConfirmModal
          product={product}
          amount={numericAmount}
          onCancel={() => setShowConfirm(false)}
          onConfirm={submit}
          submitting={confirming}
        />
      )}
    </div>
  );
}

function ProductCard({ product, active, onClick }:
  { product: Product; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid={`product-${product.product_id}`}
      className={`p-4 rounded-xl border text-left transition-all
                  ${active ? "border-primary bg-primary/5 ring-1 ring-primary"
                            : "border-border hover:bg-surface-hover"}`}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="text-sm font-display font-bold text-fg">{product.name}</div>
        <Badge tone={TONE[product.product_id] || "info"} size="sm">
          APR {fmtPct(product.apr_bps)}
        </Badge>
      </div>
      <div className="text-[11px] text-fg-muted line-clamp-2">{product.description}</div>
      <div className="mt-3 flex items-center gap-3 text-[10px] font-mono text-fg-subtle">
        <span className="inline-flex items-center gap-1">
          {product.term_days === 0
            ? <><Sparkles size={10} /> Liquid</>
            : <><Lock size={10} /> {product.term_days}d</>}
        </span>
        <span className="inline-flex items-center gap-1">
          <Coins size={10} /> min {product.min_amount}
        </span>
      </div>
    </button>
  );
}

function ConfirmModal({ product, amount, onCancel, onConfirm, submitting }:
  { product: Product; amount: number; onCancel: () => void;
    onConfirm: () => void; submitting: boolean }) {
  return (
    <div className="fixed inset-0 bg-bg/70 backdrop-blur-sm z-50 grid place-items-center p-4"
         onClick={onCancel}
         data-testid="confirm-modal">
      <div className="prosper-card p-6 max-w-md w-full" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 mb-2">
          <TrendingUp size={16} className="text-primary" />
          <h2 className="font-display font-bold text-lg text-fg">Confirmar inversión</h2>
        </div>
        <p className="text-sm text-fg-muted mb-4">
          Vas a invertir <strong>{amount.toFixed(2)} USDC</strong> en <strong>{product.name}</strong> con
          APR {fmtPct(product.apr_bps)}{product.term_days > 0
            ? ` y lock de ${product.term_days} días` : " (liquid)"}.
        </p>

        <div className="rounded border border-warning/30 bg-warning/5 p-3 text-[11px] text-fg-muted mb-5">
          <strong className="text-warning">Disclaimer:</strong> Las inversiones en Prosper Yield Token
          están sujetas a riesgo de mercado. APR es indicativo, no garantizado. Para más información
          consultá los <a href="/terms" className="text-primary hover:underline">Términos</a>.
        </div>

        <div className="flex gap-2">
          <button onClick={onCancel}
            className="prosper-btn-ghost flex-1 h-11 text-sm" data-testid="confirm-cancel">
            Cancelar
          </button>
          <button onClick={onConfirm} disabled={submitting}
            className="prosper-btn-primary flex-1 h-11 text-sm gap-2" data-testid="confirm-yes">
            {submitting ? "Procesando…" : "Confirmar"}
          </button>
        </div>
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
