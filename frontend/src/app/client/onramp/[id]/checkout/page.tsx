"use client";
import { useEffect } from "react";
import { useRouter, useParams } from "next/navigation";
import Link from "next/link";
import { ExternalLink, Loader2, ShieldCheck, X } from "lucide-react";
import { PageHeader, Badge } from "@prosper/ui";
import { useOnrampOrder, fmtCur } from "@/lib/alfred";

/**
 * /client/onramp/[id]/checkout — waiting page that:
 *  1. Opens Alfred's hosted checkout in a new tab.
 *  2. Polls /v1/client/onramp/orders/[id] every 5s (via useOnrampOrder).
 *  3. Redirects to /success or /failed when status flips.
 */
export default function OnrampCheckoutPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const id = params?.id || null;
  const { data, isLoading } = useOnrampOrder(id);
  const order = data?.order;

  // Open Alfred's checkout in a popup the first time the page mounts.
  useEffect(() => {
    if (!order || order.status !== "pending") return;
    if (typeof window === "undefined") return;
    const opened = sessionStorage.getItem(`alfred_opened_${order.onramp_id}`);
    if (!opened) {
      window.open(order.checkout_url, "_blank", "noopener,noreferrer");
      sessionStorage.setItem(`alfred_opened_${order.onramp_id}`, "1");
    }
  }, [order]);

  // Auto-navigate when settled
  useEffect(() => {
    if (!order || !id) return;
    if (order.status === "confirmed" || order.status === "completed") {
      router.replace(`/client/onramp/${id}/success`);
    } else if (order.status === "failed") {
      router.replace(`/client/onramp/${id}/failed`);
    }
  }, [order, router, id]);

  return (
    <div data-testid="onramp-checkout">
      <PageHeader
        breadcrumbs={[
          { label: "Inicio", href: "/client" },
          { label: "Cargar", href: "/client/onramp" },
          { label: "Checkout" },
        ]}
        kicker="Pago en proceso"
        title="Esperando confirmación"
        subtitle="Cuando completes el pago en Alfred, la pantalla se actualiza sola."
      />

      <div className="max-w-xl mx-auto prosper-card p-8 text-center">
        {isLoading || !order ? (
          <div className="py-10 text-fg-subtle">Cargando…</div>
        ) : (
          <>
            <div className="mx-auto h-14 w-14 rounded-full bg-primary/10 text-primary flex items-center justify-center mb-3">
              <Loader2 size={24} className="animate-spin" />
            </div>
            <h2 className="font-display font-bold text-xl text-fg">
              Esperando que confirmes el pago
            </h2>
            <p className="text-sm text-fg-muted mt-2 max-w-md mx-auto">
              Si la ventana de Alfred no se abrió, podés volver a abrirla acá.
              Esta pantalla refresca cada 5 segundos.
            </p>

            <a
              href={order.checkout_url}
              target="_blank"
              rel="noopener noreferrer"
              className="prosper-btn-primary inline-flex h-11 px-5 mt-5 text-sm gap-2"
              data-testid="checkout-open"
            >
              Abrir checkout Alfred <ExternalLink size={14} />
            </a>

            <div className="mt-6 text-left space-y-2 text-sm">
              <Row label="Pagás" value={`${order.source_amount.toLocaleString()} ${order.source_currency}`} />
              <Row label="Recibís"
                   value={fmtCur(order.expected_usdc, "USDC") + " USDC"} success />
              <Row label="Fee"  value={`${fmtCur(order.fee_amount, order.fee_currency)}`} />
              <Row label="Método de pago" value={order.payment_method} />
              <Row label="Alfred ID" value={order.alfred_id} mono small />
              <div className="flex items-center justify-between pt-2 border-t border-border">
                <span className="text-xs text-fg-muted">Status</span>
                <Badge tone="warning" size="sm" data-testid="checkout-status">{order.status}</Badge>
              </div>
              {order.mode !== "production" && (
                <div className="text-[10px] font-mono uppercase tracking-wider text-warning text-center">
                  Alfred mode: {order.mode}
                </div>
              )}
            </div>

            <Link
              href="/client/onramp"
              className="inline-flex mt-6 text-xs font-mono uppercase tracking-wider
                         text-fg-subtle hover:text-fg gap-1 items-center"
            >
              <X size={11} /> Cancelar y volver
            </Link>

            <div className="mt-5 pt-4 border-t border-border text-[10px] font-mono uppercase tracking-wider text-fg-subtle flex items-center justify-center gap-1">
              <ShieldCheck size={11} /> Powered by Alfred · KYT-screened
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Row({ label, value, success, mono, small }:
  { label: string; value: string; success?: boolean; mono?: boolean; small?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-fg-muted">{label}</span>
      <span className={`${mono || small ? "font-mono" : ""} ${small ? "text-[11px]" : "text-sm"}
                       ${success ? "text-success font-bold" : "text-fg"} break-all`}>
        {value}
      </span>
    </div>
  );
}
