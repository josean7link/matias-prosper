"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { CheckCircle2, Circle, Clock, Loader2 } from "lucide-react";
import { PageHeader, Badge } from "@prosper/ui";
import { useOfframpOrder, fmtCur } from "@/lib/alfred";

export default function OfframpStatusPage() {
  const params = useParams<{ id: string }>();
  const { data, isLoading } = useOfframpOrder(params?.id || null);
  const order = data?.order;

  return (
    <div data-testid="offramp-status">
      <PageHeader
        breadcrumbs={[
          { label: "Client", href: "/client" },
          { label: "Retirar", href: "/client/offramp" },
          { label: "Status" },
        ]}
        kicker="Retiro en proceso"
        title={order?.status === "completed" ? "Retiro acreditado" : "Retiro en proceso"}
      />

      {isLoading || !order ? (
        <div className="prosper-card p-8 text-center text-fg-subtle">Cargando…</div>
      ) : (
        <div className="max-w-2xl mx-auto space-y-5">
          <div className="prosper-card p-7 text-center">
            <div className={`mx-auto h-16 w-16 rounded-full flex items-center justify-center mb-3
                             ${order.status === "completed"
                                ? "bg-success text-white"
                                : order.status === "failed"
                                  ? "bg-danger text-white"
                                  : "bg-primary/10 text-primary"}`}>
              {order.status === "completed" ? <CheckCircle2 size={32} />
                : order.status === "failed"   ? <Circle size={32} />
                : <Loader2 size={32} className="animate-spin" />}
            </div>
            <div className="text-[10px] font-mono uppercase tracking-[0.2em]
                            text-fg-subtle">{order.target_currency} pendiente de acreditación</div>
            <h1 className="font-display font-extrabold text-4xl text-fg mt-1 tabular-nums">
              {(order.fiat_received ?? order.expected_fiat).toFixed(2)}
              <span className="text-2xl ml-2 text-fg-muted">{order.target_currency}</span>
            </h1>
            <p className="text-sm text-fg-muted mt-2 max-w-md mx-auto">
              {order.status === "completed"
                ? "Tu retiro fue acreditado en la cuenta destino."
                : "Te avisamos por email cuando el banco confirme la acreditación."}
            </p>
          </div>

          {/* Timeline */}
          <div className="prosper-card p-5" data-testid="offramp-timeline">
            <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-4">
              Timeline
            </div>
            <ol className="space-y-3">
              {order.timeline.map((step, i) => (
                <li
                  key={step.key}
                  className="flex items-start gap-3"
                  data-testid={`timeline-${step.key}`}
                  data-done={step.done}
                >
                  <div className={`shrink-0 h-7 w-7 rounded-full flex items-center justify-center
                                   ${step.done ? "bg-success text-white"
                                              : step.skipped ? "bg-surface text-fg-subtle"
                                              : "bg-warning/10 text-warning"}`}>
                    {step.done ? <CheckCircle2 size={14} />
                      : step.skipped ? <span className="text-[10px]">—</span>
                      : <Clock size={12} />}
                  </div>
                  <div className="flex-1">
                    <div className={`text-sm ${step.done ? "text-fg font-display font-semibold" : "text-fg-muted"}`}>
                      {step.label}
                    </div>
                    {!step.done && !step.skipped && i === order.timeline.findIndex((s) => !s.done) && (
                      <div className="text-[11px] text-fg-subtle">En progreso…</div>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          </div>

          {/* Detail */}
          <div className="prosper-card p-5" data-testid="offramp-detail">
            <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3 text-sm">
              <Row label="Retirás" value={`${order.usdc_sent.toFixed(2)} USDC`} />
              <Row label="Recibís" success
                   value={`${(order.fiat_received ?? order.expected_fiat).toFixed(2)} ${order.target_currency}`} />
              <Row label="Titular" value={order.bank_account.holder_name} />
              <Row label="CBU / IBAN" value={order.bank_account.cbu_or_iban || "—"} mono small />
              <Row label="Alfred ID" value={order.alfred_id} mono small />
              <Row label="Orden Prosper" value={order.offramp_id} mono small />
            </dl>
            <div className="mt-4 pt-4 border-t border-border flex items-center justify-between">
              <Badge tone={order.status === "completed" ? "success"
                          : order.status === "failed"   ? "danger"
                          : "warning"} size="sm">
                {order.status}
              </Badge>
              <Link href="/client/transactions"
                className="text-xs font-mono uppercase tracking-wider text-primary hover:underline">
                Ver historial →
              </Link>
            </div>
          </div>
        </div>
      )}
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
