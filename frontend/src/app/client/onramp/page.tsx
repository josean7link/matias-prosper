"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, useCallback, useRef } from "react";
import { toast } from "sonner";
import {
  ArrowRight, ArrowDownToLine, Wallet, Banknote, CreditCard,
  CircleDollarSign, RefreshCw, Clock, AlertTriangle, CheckCircle2,
} from "lucide-react";
import { PageHeader, Badge } from "@prosper/ui";
import { api } from "@/lib/api";
import { useClientMe } from "@/lib/client-portal";
import {
  ONRAMP_CURRENCIES, PAYMENT_METHODS, fmtCur,
  type Quote, type OnrampOrder,
} from "@/lib/alfred";

const PAYMENT_ICON = {
  transfer:    <Banknote size={14} />,
  mercadopago: <Wallet size={14} />,
  crypto:      <CircleDollarSign size={14} />,
  card:        <CreditCard size={14} />,
} as const;

export default function OnrampPage() {
  const router = useRouter();
  const { data: me } = useClientMe();
  const canOperate = me?.features?.can_operate ?? false;

  const [currency, setCurrency] = useState("ARS");
  const [amount, setAmount] = useState<string>("100000");
  const [method, setMethod]   = useState("transfer");
  const [quote, setQuote]     = useState<Quote | null>(null);
  const [loadingQuote, setLoadingQuote] = useState(false);
  const [secs, setSecs]       = useState(60);
  const [submitting, setSubmitting] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const numericAmount = Number(amount) || 0;

  const refreshQuote = useCallback(async () => {
    if (numericAmount <= 0) { setQuote(null); return; }
    setLoadingQuote(true);
    try {
      const q = await api<Quote>("/v1/client/onramp/quote", {
        method: "POST",
        body: JSON.stringify({ source_currency: currency,
                                source_amount: numericAmount }),
      });
      setQuote(q);
      setSecs(q.ttl_seconds);
    } catch (err) {
      const e = err as Error;
      setQuote(null);
      toast.error(e.message || "No pude cotizar");
    } finally {
      setLoadingQuote(false);
    }
  }, [currency, numericAmount]);

  // Re-quote when currency/amount changes (debounced 600ms)
  useEffect(() => {
    if (!canOperate) return;
    const t = setTimeout(() => { refreshQuote(); }, 600);
    return () => clearTimeout(t);
  }, [refreshQuote, canOperate]);

  // Countdown
  useEffect(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    if (!quote) return;
    timerRef.current = setInterval(() => {
      setSecs((s) => {
        if (s <= 1) { refreshQuote(); return quote.ttl_seconds; }
        return s - 1;
      });
    }, 1000);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [quote, refreshQuote]);

  const submit = async () => {
    if (!quote) return;
    setSubmitting(true);
    try {
      const res = await api<{ order: OnrampOrder }>(
        "/v1/client/onramp/orders",
        { method: "POST", body: JSON.stringify({
            quote_id: quote.quote_id,
            source_currency: currency,
            source_amount: numericAmount,
            payment_method: method,
          }) }
      );
      toast.success("Orden creada — redirigiendo a checkout");
      router.push(`/client/onramp/${res.order.onramp_id}/checkout`);
    } catch (err) {
      const e = err as Error;
      toast.error(e.message || "Error al crear la orden");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div data-testid="onramp-page">
      <PageHeader
        breadcrumbs={[{ label: "Client", href: "/client" }, { label: "Cargar dinero" }]}
        kicker="Phase 8 · Alfred onramp"
        title="Cargar dinero"
        subtitle="Convertimos tu transferencia a USDC en pocos minutos."
      />

      {!canOperate ? (
        <BlockedCard />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
          {/* LEFT — Form */}
          <div className="lg:col-span-3 space-y-5" data-testid="onramp-form">
            {/* Currency */}
            <FieldBlock label="1. Moneda de origen">
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                {ONRAMP_CURRENCIES.map((c) => (
                  <button
                    key={c.code}
                    type="button"
                    onClick={() => setCurrency(c.code)}
                    className={`p-3 rounded-lg border text-left transition-all
                                ${currency === c.code
                                  ? "border-primary bg-primary/5 ring-1 ring-primary"
                                  : "border-border hover:bg-surface-hover"}`}
                    data-testid={`currency-${c.code}`}
                  >
                    <div className="text-xl">{c.flag}</div>
                    <div className="text-sm font-display font-bold mt-1">{c.code}</div>
                    <div className="text-[10px] text-fg-subtle">{c.label}</div>
                  </button>
                ))}
              </div>
            </FieldBlock>

            {/* Amount */}
            <FieldBlock label="2. Monto en moneda local">
              <div className="relative">
                <input
                  type="number"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  placeholder="100000"
                  className="prosper-input w-full h-14 text-3xl font-display font-bold pr-20"
                  data-testid="onramp-amount"
                />
                <span className="absolute right-4 top-1/2 -translate-y-1/2 text-sm font-mono
                                 uppercase tracking-wider text-fg-subtle">
                  {currency}
                </span>
              </div>
            </FieldBlock>

            {/* Payment method */}
            <FieldBlock label="3. Método de pago">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {PAYMENT_METHODS.map((p) => (
                  <button
                    key={p.code}
                    type="button"
                    onClick={() => setMethod(p.code)}
                    className={`p-3 rounded-lg border text-left transition-all flex items-center gap-3
                                ${method === p.code
                                  ? "border-primary bg-primary/5 ring-1 ring-primary"
                                  : "border-border hover:bg-surface-hover"}`}
                    data-testid={`pm-${p.code}`}
                  >
                    <div className="h-9 w-9 rounded-full bg-primary/10 text-primary flex items-center justify-center">
                      {PAYMENT_ICON[p.code as keyof typeof PAYMENT_ICON]}
                    </div>
                    <div className="flex-1">
                      <div className="text-sm font-display font-semibold text-fg">{p.label}</div>
                      <div className="text-[11px] text-fg-subtle">{p.hint}</div>
                    </div>
                  </button>
                ))}
              </div>
            </FieldBlock>
          </div>

          {/* RIGHT — Live quote */}
          <div className="lg:col-span-2">
            <div className="prosper-card p-5 sticky top-20" data-testid="quote-card">
              <div className="flex items-center justify-between mb-3">
                <div>
                  <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
                    Cotización Alfred
                  </div>
                  <h3 className="font-display font-bold text-lg text-fg mt-0.5">
                    Resumen en vivo
                  </h3>
                </div>
                {quote && (
                  <Badge tone={secs > 15 ? "info" : "warning"} size="sm">
                    <Clock size={10} className="mr-1" />
                    <span data-testid="quote-countdown">{secs}s</span>
                  </Badge>
                )}
              </div>

              {!quote ? (
                <div className="py-8 text-center text-fg-subtle text-sm">
                  {loadingQuote ? "Cotizando…" :
                   numericAmount <= 0 ? "Ingresá un monto para cotizar" :
                   "Sin cotización"}
                </div>
              ) : (
                <>
                  <div className="space-y-2 text-sm">
                    <Row label="Pagás" value={`${numericAmount.toLocaleString()} ${currency}`} muted />
                    <Row label="Rate" value={`1 ${currency} = ${quote.rate.toFixed(6)} USDC`} small />
                    <Row label="Fee" value={`− ${fmtCur(quote.fee_amount, quote.fee_currency)}`} small danger />
                    <div className="h-px bg-border my-3" />
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-fg-muted">Recibís</span>
                      <span className="text-2xl font-display font-extrabold text-success font-mono tabular-nums"
                            data-testid="quote-target">
                        {quote.target_amount.toFixed(2)} USDC
                      </span>
                    </div>
                  </div>

                  {quote.mode !== "production" && (
                    <div className="mt-4 rounded border border-warning/30 bg-warning/5 p-2.5 flex items-start gap-2">
                      <AlertTriangle size={14} className="text-warning shrink-0 mt-0.5" />
                      <div className="text-[11px] text-fg-muted">
                        Modo <strong>{quote.mode}</strong>. Cotización simulada hasta tener credenciales reales de Alfred.
                      </div>
                    </div>
                  )}

                  <button
                    onClick={submit}
                    disabled={submitting || secs <= 0}
                    className="prosper-btn-primary w-full h-12 mt-5 text-sm gap-2 disabled:opacity-40"
                    data-testid="onramp-confirm"
                  >
                    {submitting ? "Creando orden…" :
                      (<>Confirmar y pagar <ArrowRight size={14} /></>)}
                  </button>

                  <button
                    onClick={refreshQuote}
                    disabled={loadingQuote}
                    className="w-full mt-2 text-[11px] font-mono uppercase tracking-wider
                               text-fg-subtle hover:text-fg flex items-center justify-center gap-1"
                    data-testid="quote-refresh"
                  >
                    <RefreshCw size={11} className={loadingQuote ? "animate-spin" : ""} />
                    Refrescar cotización
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function BlockedCard() {
  return (
    <div className="prosper-card p-10 text-center" data-testid="onramp-blocked">
      <div className="mx-auto h-12 w-12 rounded-full bg-warning/10 text-warning flex items-center justify-center mb-3">
        <AlertTriangle size={20} />
      </div>
      <h2 className="font-display font-bold text-lg text-fg">Onboarding pendiente</h2>
      <p className="text-sm text-fg-muted mt-2 max-w-sm mx-auto">
        Tu KYB todavía no fue aprobado. Una vez aprobado, vas a poder cargar
        fondos en USDC al instante.
      </p>
      <Link href="/apply" className="prosper-btn-primary inline-flex h-10 px-5 mt-5 text-sm">
        Continuar onboarding <ArrowRight size={14} />
      </Link>
    </div>
  );
}

function FieldBlock({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section>
      <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-2">
        {label}
      </div>
      {children}
    </section>
  );
}

function Row({ label, value, muted, small, danger }:
  { label: string; value: string; muted?: boolean; small?: boolean; danger?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className={`${small ? "text-xs" : "text-sm"} text-fg-muted`}>{label}</span>
      <span className={`font-mono tabular-nums ${small ? "text-xs" : "text-sm"}
                       ${danger ? "text-warning" : muted ? "text-fg-muted" : "text-fg"}`}>
        {value}
      </span>
    </div>
  );
}
