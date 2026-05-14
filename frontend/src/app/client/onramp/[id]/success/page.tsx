"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { CheckCircle2, Plus, ArrowRight, Sparkles, TrendingUp, ExternalLink } from "lucide-react";
import { PageHeader, Badge } from "@prosper/ui";
import { useOnrampOrder, fmtCur } from "@/lib/alfred";
import { fmtPct, STELLAR_EXPLORER } from "@/lib/invest";

/**
 * /client/onramp/[id]/success — celebratory landing after Alfred confirms.
 * Also shows the auto-buy result (transaction + position) when present.
 */
export default function OnrampSuccessPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id || null;
  const { data } = useOnrampOrder(id);
  const order = data?.order;
  const subTx = data?.subscribe_tx;
  const position = data?.position;

  if (!order) {
    return (
      <div className="prosper-card p-8 text-center text-fg-subtle">Cargando…</div>
    );
  }

  return (
    <div data-testid="onramp-success">
      <PageHeader
        breadcrumbs={[
          { label: "Client", href: "/client" },
          { label: "Cargar", href: "/client/onramp" },
          { label: "Confirmación" },
        ]}
        kicker="Operación completada"
        title="¡Carga completada!"
      />

      <div className="max-w-2xl mx-auto">
        {/* Hero */}
        <div className="prosper-card p-10 text-center relative overflow-hidden"
             data-testid="success-hero">
          <div className="absolute inset-0 bg-gradient-to-b from-success/8 to-transparent pointer-events-none" />
          <div className="relative">
            <div className="mx-auto h-20 w-20 rounded-full bg-success text-white flex items-center justify-center shadow-lg">
              <CheckCircle2 size={36} strokeWidth={2.5} />
            </div>
            <div className="mt-5 text-[10px] font-mono uppercase tracking-[0.2em] text-success">
              + {(order.usdc_received ?? order.expected_usdc).toFixed(2)} USDC acreditado
            </div>
            <h1 className="font-display font-black text-4xl text-fg tracking-tight mt-1">
              {(order.usdc_received ?? order.expected_usdc).toFixed(2)}
              <span className="text-2xl ml-2 text-fg-muted">USDC</span>
            </h1>
            <p className="text-sm text-fg-muted mt-3 max-w-md mx-auto">
              {position
                ? "Tus dólares Prosper ya están trabajando y generando yield."
                : "Tus dólares Prosper ya están disponibles en tu cuenta."}
            </p>

            <div className="mt-6 flex flex-col sm:flex-row gap-2 justify-center">
              {position ? (
                <Link
                  href={`/client/investments/${position.position_id}`}
                  className="prosper-btn-primary h-11 px-6 text-sm gap-2 justify-center"
                  data-testid="success-position"
                >
                  <TrendingUp size={14} />
                  Ver mi posición
                </Link>
              ) : (
                <Link
                  href="/client/invest"
                  className="prosper-btn-primary h-11 px-6 text-sm gap-2 justify-center"
                  data-testid="success-invest"
                >
                  <Sparkles size={14} />
                  Empezar a invertir
                </Link>
              )}
              <Link
                href="/client/onramp"
                className="prosper-btn-ghost h-11 px-6 text-sm gap-2 justify-center"
                data-testid="success-again"
              >
                <Plus size={14} />
                Hacer otra carga
              </Link>
            </div>
          </div>
        </div>

        {/* AUTO-BUY card (Phase 9) */}
        {subTx && position && (
          <div className="prosper-card p-6 mt-5 border-success/30 relative overflow-hidden"
               data-testid="success-auto-buy">
            <div className="absolute -top-3 left-6">
              <Badge tone="success" size="sm">
                <Sparkles size={10} className="mr-1" />
                Compra automática Prosper
              </Badge>
            </div>
            <div className="mt-2 flex items-center justify-between mb-4">
              <div>
                <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
                  Token recibido
                </div>
                <div className="text-2xl font-display font-extrabold font-mono tabular-nums text-fg">
                  {subTx.amount.toFixed(2)} <span className="text-sm text-fg-muted">PROS</span>
                </div>
              </div>
              <div className="text-right">
                <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
                  APR
                </div>
                <div className="text-2xl font-display font-extrabold font-mono text-success tabular-nums">
                  {fmtPct(position.apr_bps)}
                </div>
              </div>
            </div>

            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs">
              <Row label="Producto" value={position.product_id} mono />
              <Row label="Status"   value={position.status}      badge="success" />
              <Row label="Maturity"
                    value={position.maturity ? position.maturity.slice(0, 10) : "Liquid · sin lock"}
                    mono />
              {subTx.tx_hash && (
                <div>
                  <dt className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
                    Stellar tx
                  </dt>
                  <dd>
                    <a href={`${STELLAR_EXPLORER}/${subTx.tx_hash}`}
                       target="_blank" rel="noopener noreferrer"
                       className="text-[10px] font-mono text-primary hover:underline
                                  inline-flex items-center gap-1">
                      {subTx.tx_hash.slice(0, 14)}… <ExternalLink size={9}/>
                    </a>
                  </dd>
                </div>
              )}
            </dl>
          </div>
        )}

        {/* Onramp detail */}
        <div className="prosper-card p-6 mt-5" data-testid="success-detail">
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-3">
            Detalle del onramp
          </div>
          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3 text-sm">
            <RowBlock label="Monto cargado" value={`${order.source_amount.toLocaleString()} ${order.source_currency}`} />
            <RowBlock label="USDC recibido"
                       value={fmtCur(order.usdc_received ?? order.expected_usdc, "USDC") + " USDC"}
                       success />
            <RowBlock label="Fee" value={fmtCur(order.fee_amount, order.fee_currency)} />
            <RowBlock label="Rate"
                       value={`1 ${order.source_currency} = ${order.rate.toFixed(6)} USDC`} small />
            <RowBlock label="Alfred ID"     value={order.alfred_id} mono small />
            {order.coelsa_id && (
              <RowBlock label="Coelsa ID" value={order.coelsa_id} mono small />
            )}
            <RowBlock label="Orden Prosper" value={order.onramp_id} mono small />
            <div>
              <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-1">
                Status
              </div>
              <Badge tone="success" size="sm">{order.status}</Badge>
            </div>
          </dl>

          <div className="mt-5 pt-4 border-t border-border flex items-center justify-between">
            <Link
              href="/client/transactions"
              className="text-xs font-mono uppercase tracking-wider text-primary hover:underline
                         flex items-center gap-1"
              data-testid="success-history"
            >
              Ver historial <ArrowRight size={11} />
            </Link>
            <Link
              href="/client"
              className="text-xs font-mono uppercase tracking-wider text-fg-subtle hover:text-fg"
            >
              Volver al dashboard
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}

function RowBlock({ label, value, success, mono, small }:
  { label: string; value: string; success?: boolean; mono?: boolean; small?: boolean }) {
  return (
    <div>
      <dt className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-1">
        {label}
      </dt>
      <dd className={`${mono || small ? "font-mono" : ""} ${small ? "text-xs" : "text-sm"}
                     ${success ? "text-success font-bold" : "text-fg"} break-all`}>
        {value}
      </dd>
    </div>
  );
}

function Row({ label, value, mono, badge }:
  { label: string; value: string; mono?: boolean; badge?: "success" }) {
  return (
    <div>
      <dt className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">{label}</dt>
      <dd className={`text-xs ${mono ? "font-mono" : ""} text-fg break-all`}>
        {badge ? <Badge tone={badge} size="sm">{value}</Badge> : value}
      </dd>
    </div>
  );
}
