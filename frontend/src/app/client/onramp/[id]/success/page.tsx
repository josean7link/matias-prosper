"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { CheckCircle2, Plus, ArrowRight, Sparkles } from "lucide-react";
import { PageHeader, Badge } from "@prosper/ui";
import { useOnrampOrder, fmtCur } from "@/lib/alfred";

/**
 * /client/onramp/[id]/success — celebratory landing page after Alfred confirms.
 * Inspired by mockup "+1200 usd USDC Prosper Disponible!".
 */
export default function OnrampSuccessPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id || null;
  const { data } = useOnrampOrder(id);
  const order = data?.order;

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
              Tus dólares Prosper ya están disponibles en tu cuenta.
              Listos para empezar a generar yield.
            </p>

            <div className="mt-6 flex flex-col sm:flex-row gap-2 justify-center">
              <Link
                href="/client/investments"
                className="prosper-btn-primary h-11 px-6 text-sm gap-2 justify-center"
                data-testid="success-invest"
              >
                <Sparkles size={14} />
                Empezar a invertir
              </Link>
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

        {/* Detail */}
        <div className="prosper-card p-6 mt-5" data-testid="success-detail">
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-3">
            Detalle de la operación
          </div>
          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3 text-sm">
            <Row label="Monto cargado" value={`${order.source_amount.toLocaleString()} ${order.source_currency}`} />
            <Row label="USDC recibido"
                 value={fmtCur(order.usdc_received ?? order.expected_usdc, "USDC") + " USDC"}
                 success />
            <Row label="Fee" value={fmtCur(order.fee_amount, order.fee_currency)} />
            <Row label="Rate"
                 value={`1 ${order.source_currency} = ${order.rate.toFixed(6)} USDC`} small />
            <Row label="Alfred ID"     value={order.alfred_id} mono small />
            {order.coelsa_id && (
              <Row label="Coelsa ID" value={order.coelsa_id} mono small />
            )}
            <Row label="Orden Prosper" value={order.onramp_id} mono small />
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

function Row({ label, value, success, mono, small }:
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
