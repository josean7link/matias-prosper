"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { XCircle, ArrowLeft } from "lucide-react";
import { PageHeader } from "@prosper/ui";
import { useOnrampOrder } from "@/lib/alfred";

export default function OnrampFailedPage() {
  const params = useParams<{ id: string }>();
  const { data } = useOnrampOrder(params?.id || null);
  const order = data?.order;

  return (
    <div data-testid="onramp-failed">
      <PageHeader
        breadcrumbs={[
          { label: "Inicio", href: "/client" },
          { label: "Cargar", href: "/client/onramp" },
          { label: "Error" },
        ]}
        kicker="Operación cancelada"
        title="La carga no se completó"
      />

      <div className="max-w-md mx-auto prosper-card p-8 text-center">
        <div className="mx-auto h-14 w-14 rounded-full bg-danger/10 text-danger flex items-center justify-center mb-3">
          <XCircle size={28} />
        </div>
        <h2 className="font-display font-bold text-lg text-fg">
          El pago no se confirmó
        </h2>
        <p className="text-sm text-fg-muted mt-2">
          Si confirmaste el pago pero seguís viendo este mensaje, esperá unos
          minutos y volvé a revisar el historial. Si necesitás ayuda, escribinos.
        </p>
        {order && (
          <div className="mt-5 text-left text-xs space-y-1 font-mono text-fg-subtle">
            <div>onramp_id · {order.onramp_id}</div>
            <div>alfred_id · {order.alfred_id}</div>
          </div>
        )}
        <Link
          href="/client/onramp"
          className="prosper-btn-primary inline-flex h-10 px-5 mt-5 text-sm gap-2"
          data-testid="failed-retry"
        >
          <ArrowLeft size={14} /> Intentar de nuevo
        </Link>
      </div>
    </div>
  );
}
