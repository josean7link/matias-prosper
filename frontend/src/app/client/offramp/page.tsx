"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, useCallback, useRef } from "react";
import { toast } from "sonner";
import {
  ArrowRight, ArrowUpFromLine, AlertTriangle, Clock, RefreshCw, Coins, Wallet,
} from "lucide-react";
import { PageHeader, Badge } from "@prosper/ui";
import { api } from "@/lib/api";
import { useClientMe } from "@/lib/client-portal";
import { useClientDashboard } from "@/lib/client-portal";
import { ONRAMP_CURRENCIES, fmtCur, type Quote, type OfframpOrder } from "@/lib/alfred";

const TARGETS = ONRAMP_CURRENCIES.filter((c) => c.code !== "USDC");

export default function OfframpPage() {
  const router = useRouter();
  const { data: me } = useClientMe();
  const { data: dash } = useClientDashboard();
  const canOperate = me?.features?.can_operate ?? false;
  const balance = dash?.kpis?.available_usdc ?? 0;

  const [source, setSource] = useState<"balance" | "position">("balance");
  const [amount, setAmount] = useState<string>("");
  const [target, setTarget] = useState("ARS");
  const [holderName, setHolderName] = useState(me?.org?.legal_name || "");
  const [bankAlias,  setBankAlias]  = useState("");
  const [cbu, setCbu] = useState("");
  const [bankName, setBankName] = useState("");
  const [quote, setQuote] = useState<Quote | null>(null);
  const [secs, setSecs]   = useState(60);
  const [submitting, setSubmitting] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const numericAmount = Number(amount) || 0;
  const insufficient  = source === "balance" && numericAmount > balance;

  useEffect(() => {
    if (me?.org?.legal_name && !holderName) setHolderName(me.org.legal_name);
  }, [me, holderName]);

  const refreshQuote = useCallback(async () => {
    if (numericAmount <= 0) { setQuote(null); return; }
    try {
      const q = await api<Quote>("/v1/client/offramp/quote", {
        method: "POST",
        body: JSON.stringify({ usdc_amount: numericAmount, target_currency: target }),
      });
      setQuote(q);
      setSecs(q.ttl_seconds);
    } catch (err) {
      const e = err as Error;
      toast.error(e.message || "No pude cotizar");
    }
  }, [numericAmount, target]);

  useEffect(() => {
    if (!canOperate) return;
    const t = setTimeout(refreshQuote, 600);
    return () => clearTimeout(t);
  }, [refreshQuote, canOperate]);

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

  const canSubmit = quote && !insufficient && holderName.trim() &&
                    cbu.trim() && numericAmount > 0;

  const submit = async () => {
    if (!quote || !canSubmit) return;
    setSubmitting(true);
    try {
      const res = await api<{ order: OfframpOrder }>("/v1/client/offramp/orders", {
        method: "POST",
        body: JSON.stringify({
          quote_id: quote.quote_id,
          usdc_amount: numericAmount,
          target_currency: target,
          source,
          bank_account: {
            holder_name: holderName,
            country: target === "ARS" ? "AR" : "US",
            cbu_or_iban: cbu,
            bank_name: bankName,
            account_alias: bankAlias,
          },
        }),
      });
      toast.success("Orden de retiro creada");
      router.push(`/client/offramp/${res.order.offramp_id}/status`);
    } catch (err) {
      const e = err as Error;
      toast.error(e.message || "Error al crear el retiro");
    } finally {
      setSubmitting(false);
    }
  };

  if (!canOperate) {
    return (
      <>
        <PageHeader
          breadcrumbs={[{ label: "Client", href: "/client" }, { label: "Retirar" }]}
          kicker="Phase 8 · Alfred offramp"
          title="Retirar dinero"
        />
        <div className="prosper-card p-10 text-center" data-testid="offramp-blocked">
          <div className="mx-auto h-12 w-12 rounded-full bg-warning/10 text-warning flex items-center justify-center mb-3">
            <AlertTriangle size={20} />
          </div>
          <h2 className="font-display font-bold text-lg text-fg">Onboarding pendiente</h2>
          <p className="text-sm text-fg-muted mt-2">Aprobá tu KYB para empezar a operar.</p>
          <Link href="/apply" className="prosper-btn-primary inline-flex h-10 px-5 mt-5 text-sm">
            Continuar onboarding <ArrowRight size={14} />
          </Link>
        </div>
      </>
    );
  }

  if (balance <= 0 && source === "balance") {
    return (
      <>
        <PageHeader
          breadcrumbs={[{ label: "Client", href: "/client" }, { label: "Retirar" }]}
          kicker="Phase 8 · Alfred offramp"
          title="Retirar dinero"
        />
        <div className="prosper-card p-10 text-center" data-testid="offramp-empty">
          <Wallet size={28} className="mx-auto text-fg-subtle mb-2" />
          <h2 className="font-display font-bold text-lg text-fg">No tenés saldo libre</h2>
          <p className="text-sm text-fg-muted mt-2 max-w-sm mx-auto">
            Tu saldo USDC disponible es $0. Si tenés posiciones, podés rescatarlas antes de retirar.
          </p>
          <button
            onClick={() => setSource("position")}
            className="prosper-btn-ghost inline-flex h-10 px-5 mt-5 text-sm"
            data-testid="offramp-redeem-mode"
          >
            <Coins size={14} className="mr-1" />
            Redimir una posición
          </button>
        </div>
      </>
    );
  }

  return (
    <div data-testid="offramp-page">
      <PageHeader
        breadcrumbs={[{ label: "Client", href: "/client" }, { label: "Retirar" }]}
        kicker="Phase 8 · Alfred offramp"
        title="Retirar dinero"
        subtitle="Convertimos tu USDC a fiat y lo enviamos a tu cuenta bancaria."
      />

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* LEFT */}
        <div className="lg:col-span-3 space-y-5" data-testid="offramp-form">
          {/* Source tabs */}
          <FieldBlock label="1. Origen de fondos">
            <div className="grid grid-cols-2 gap-2">
              <button type="button" onClick={() => setSource("balance")}
                className={tabClass(source === "balance")}
                data-testid="source-balance">
                <Wallet size={14} /> Saldo libre
                <div className="ml-auto text-[11px] font-mono">{fmtCur(balance, "USDC")}</div>
              </button>
              <button type="button" onClick={() => setSource("position")}
                className={tabClass(source === "position")}
                data-testid="source-position">
                <Coins size={14} /> Redimir posición
                <span className="ml-auto text-[10px] font-mono uppercase opacity-60">soon</span>
              </button>
            </div>
            {source === "position" && (
              <p className="mt-2 text-[11px] text-warning">
                Los rescates completos llegan en Fase 9. Por ahora elegí "Saldo libre".
              </p>
            )}
          </FieldBlock>

          {/* Amount */}
          <FieldBlock label="2. Monto USDC a retirar">
            <div className="relative">
              <input
                type="number"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="100.00"
                className="prosper-input w-full h-14 text-3xl font-display font-bold pr-20"
                data-testid="offramp-amount"
              />
              <span className="absolute right-4 top-1/2 -translate-y-1/2 text-sm font-mono
                                uppercase tracking-wider text-fg-subtle">USDC</span>
            </div>
            {insufficient && (
              <p className="mt-1 text-[11px] text-danger" data-testid="offramp-insufficient">
                Excede tu saldo disponible ({fmtCur(balance, "USDC")}).
              </p>
            )}
            <button type="button"
              onClick={() => setAmount(String(balance))}
              className="mt-1 text-[11px] font-mono uppercase tracking-wider text-primary hover:underline">
              Usar máximo · {fmtCur(balance, "USDC")}
            </button>
          </FieldBlock>

          {/* Target currency */}
          <FieldBlock label="3. Moneda destino">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {TARGETS.map((c) => (
                <button key={c.code} type="button" onClick={() => setTarget(c.code)}
                  className={`p-3 rounded-lg border text-left transition-all
                              ${target === c.code
                                ? "border-primary bg-primary/5 ring-1 ring-primary"
                                : "border-border hover:bg-surface-hover"}`}
                  data-testid={`target-${c.code}`}>
                  <div className="text-lg">{c.flag}</div>
                  <div className="text-sm font-display font-bold">{c.code}</div>
                </button>
              ))}
            </div>
          </FieldBlock>

          {/* Bank account */}
          <FieldBlock label="4. Cuenta destino">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <Input label="Titular *" value={holderName} onChange={setHolderName} testid="holder-name"
                hint={`Debe coincidir con: ${me?.org?.legal_name || "—"}`} />
              <Input label="CBU / IBAN *" value={cbu} onChange={setCbu} testid="cbu" />
              <Input label="Banco" value={bankName} onChange={setBankName} testid="bank-name" />
              <Input label="Alias" value={bankAlias} onChange={setBankAlias} testid="alias" />
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
                <h3 className="font-display font-bold text-lg text-fg mt-0.5">Resumen</h3>
              </div>
              {quote && (
                <Badge tone={secs > 15 ? "info" : "warning"} size="sm">
                  <Clock size={10} className="mr-1" /><span data-testid="quote-countdown">{secs}s</span>
                </Badge>
              )}
            </div>

            {!quote ? (
              <div className="py-8 text-center text-fg-subtle text-sm">
                Ingresá un monto para cotizar
              </div>
            ) : (
              <>
                <div className="space-y-2 text-sm">
                  <Row label="Retirás" value={`${numericAmount.toFixed(2)} USDC`} muted />
                  <Row label="Rate" value={`1 USDC = ${quote.rate.toFixed(2)} ${target}`} small />
                  <Row label="Fee" value={`− ${fmtCur(quote.fee_amount, quote.fee_currency)}`} danger small />
                  <div className="h-px bg-border my-3" />
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-fg-muted">Recibís</span>
                    <span className="text-2xl font-display font-extrabold text-success font-mono tabular-nums"
                          data-testid="quote-target">
                      {quote.target_amount.toFixed(2)} {target}
                    </span>
                  </div>
                </div>

                <button onClick={submit} disabled={!canSubmit || submitting}
                  className="prosper-btn-primary w-full h-12 mt-5 text-sm gap-2 disabled:opacity-40"
                  data-testid="offramp-confirm">
                  {submitting ? "Creando orden…" : (<><ArrowUpFromLine size={14}/> Confirmar retiro</>)}
                </button>
                <button onClick={refreshQuote}
                  className="w-full mt-2 text-[11px] font-mono uppercase tracking-wider
                             text-fg-subtle hover:text-fg flex items-center justify-center gap-1"
                  data-testid="quote-refresh">
                  <RefreshCw size={11} /> Refrescar
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function tabClass(active: boolean) {
  return `flex items-center gap-2 p-3 rounded-lg border text-sm font-display font-semibold transition-all
          ${active ? "border-primary bg-primary/5 ring-1 ring-primary text-fg"
                    : "border-border hover:bg-surface-hover text-fg-muted"}`;
}

function FieldBlock({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section>
      <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-2">{label}</div>
      {children}
    </section>
  );
}

function Input({ label, value, onChange, testid, hint }:
  { label: string; value: string; onChange: (v: string) => void; testid: string; hint?: string }) {
  return (
    <label className="block">
      <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-1">{label}</div>
      <input value={value} onChange={(e) => onChange(e.target.value)}
        className="prosper-input w-full h-10 text-sm"
        data-testid={`offramp-${testid}`} />
      {hint && <div className="text-[10px] text-fg-subtle mt-1">{hint}</div>}
    </label>
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
