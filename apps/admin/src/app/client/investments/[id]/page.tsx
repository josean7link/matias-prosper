"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import {
  Coins, Lock, Sparkles, CheckCircle2, Clock, AlertTriangle,
  ArrowDownToLine, ExternalLink,
} from "lucide-react";
import { PageHeader, Badge } from "@prosper/ui";
import { fmtCur } from "@/lib/alfred";
import { api } from "@/lib/api";
import { usePosition, fmtPct, STELLAR_EXPLORER } from "@/lib/invest";

const STATUS_TONE: Record<string, "success" | "warning" | "default"> = {
  active:   "success",
  matured:  "warning",
  redeemed: "default",
};

const EVENT_LABEL: Record<string, string> = {
  subscribe:     "Suscripción",
  redeem:        "Rescate",
  yield_accrual: "Yield acumulado",
};

export default function PositionDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { data, isLoading, mutate } = usePosition(params?.id || null);
  const [redeeming, setRedeeming] = useState(false);

  const pos = data?.position;
  const events = data?.events ?? [];

  const canRedeem = pos && (
    pos.status === "matured" ||
    (pos.status === "active" && !pos.maturity)   // liquid
  );

  const totalAtMaturity = pos
    ? pos.principal_usd + (pos.accrued_interest || 0)
    : 0;

  const daysActive = pos
    ? Math.max(1, Math.floor((Date.now() - new Date(pos.start).getTime()) / 86400_000))
    : 0;

  const onRedeem = async () => {
    if (!pos) return;
    if (!window.confirm(
      `¿Confirmás el rescate de ${fmtCur(totalAtMaturity, "USDC")}?`
    )) return;
    setRedeeming(true);
    try {
      const res = await api<{ ok: boolean; amount_received: number; tx_hash: string }>(
        `/v1/client/positions/${pos.position_id}/redeem`,
        { method: "POST" });
      toast.success(`Rescate confirmado · ${fmtCur(res.amount_received, "USDC")}`);
      mutate();
      router.push("/client/transactions");
    } catch (err) {
      const e = err as Error;
      toast.error(e.message || "Error al rescatar");
    } finally {
      setRedeeming(false);
    }
  };

  if (isLoading || !pos) {
    return <div className="prosper-card p-8 text-center text-fg-subtle">Cargando…</div>;
  }

  return (
    <div data-testid="position-detail">
      <PageHeader
        breadcrumbs={[
          { label: "Inicio", href: "/client" },
          { label: "Inversiones", href: "/client/investments" },
          { label: pos.position_id.slice(0, 12) },
        ]}
        kicker={`Posición · ${pos.status}`}
        title={pos.product_id}
        subtitle={pos.maturity
          ? `Vence ${pos.maturity.slice(0, 10)}`
          : "Sin maturity registrado"}
        actions={
          canRedeem ? (
            <button
              onClick={onRedeem}
              disabled={redeeming}
              className="prosper-btn-primary h-9 px-3 text-xs gap-1.5"
              data-testid="position-redeem">
              <ArrowDownToLine size={13} />
              {redeeming ? "Procesando…" : "Redimir"}
            </button>
          ) : null
        }
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5 mb-6">
        <Kpi label="Principal" value={fmtCur(pos.principal_usd, "USDC")} />
        <Kpi label="Accrued yield" value={fmtCur(pos.accrued_interest || 0, "USDC")} success />
        <Kpi label="APR" value={fmtPct(pos.apr_bps)} success />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-5">
        {/* Timeline */}
        <section className="prosper-card p-5 lg:col-span-3" data-testid="events-timeline">
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
            Lifecycle
          </div>
          <h3 className="font-display font-bold text-lg text-fg mt-0.5 mb-4">Eventos</h3>

          {events.length === 0 ? (
            <p className="text-sm text-fg-subtle py-6 text-center">
              Aún no hay eventos registrados.
            </p>
          ) : (
            <ol className="space-y-3">
              {events.map((e) => (
                <li key={e.tx_id}
                    className="flex items-start gap-3"
                    data-testid={`event-${e.tx_id}`}>
                  <div className={`shrink-0 h-8 w-8 rounded-full flex items-center justify-center
                                   ${e.status === "confirmed" ? "bg-success/10 text-success"
                                   : e.status === "failed"    ? "bg-danger/10 text-danger"
                                   : "bg-warning/10 text-warning"}`}>
                    {e.status === "confirmed" ? <CheckCircle2 size={14} />
                     : e.status === "failed"  ? <AlertTriangle size={14} />
                     : <Clock size={14} />}
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-display font-semibold text-fg">
                        {EVENT_LABEL[e.type] || e.type}
                      </span>
                      <Badge tone={e.status === "confirmed" ? "success"
                                : e.status === "failed" ? "danger" : "warning"} size="sm">
                        {e.status}
                      </Badge>
                    </div>
                    <div className="text-xs text-fg-muted mt-0.5">
                      {fmtCur(e.amount, "USDC")} · {new Date(e.created_at).toLocaleString()}
                    </div>
                    {e.tx_hash && (
                      <a href={`${STELLAR_EXPLORER}/${e.tx_hash}`}
                          target="_blank" rel="noopener noreferrer"
                          className="text-[10px] font-mono text-primary hover:underline
                                     inline-flex items-center gap-1 mt-1">
                        {e.tx_hash.slice(0, 12)}… <ExternalLink size={9}/>
                      </a>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          )}
        </section>

        {/* Right column */}
        <section className="lg:col-span-2 space-y-4">
          <div className="prosper-card p-5">
            <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-3">
              Detalle
            </div>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
              <Row label="Position ID" value={pos.position_id} mono />
              <Row label="Status" badge={STATUS_TONE[pos.status]} value={pos.status} />
              <Row label="Inicio" value={pos.start.slice(0, 10)} mono />
              {pos.maturity && <Row label="Maturity" value={pos.maturity.slice(0, 10)} mono />}
              <Row label="Días activa" value={`${daysActive}`} />
              <Row label="prosper_tx_id" value={pos.prosper_tx_id} mono small />
              <Row label="Valor actual" value={fmtCur(totalAtMaturity, "USDC")} success />
            </dl>
          </div>

          {canRedeem ? (
            <div className="rounded-xl border border-success/40 bg-success/5 p-4">
              <div className="flex items-center gap-2 text-success mb-1">
                <Sparkles size={14} />
                <span className="text-xs font-display font-bold uppercase tracking-wider">
                  Listo para redimir
                </span>
              </div>
              <p className="text-xs text-fg-muted">
                Al redimir recibirás {fmtCur(totalAtMaturity, "USDC")} en tu saldo USDC libre.
              </p>
            </div>
          ) : pos.status === "active" && pos.maturity ? (
            <div className="rounded-xl border border-warning/30 bg-warning/5 p-4">
              <div className="flex items-center gap-2 text-warning mb-1">
                <Lock size={14} />
                <span className="text-xs font-display font-bold uppercase tracking-wider">
                  Lock activo
                </span>
              </div>
              <p className="text-xs text-fg-muted">
                Vas a poder redimir el {pos.maturity.slice(0, 10)}.
                Mientras tanto, el yield se acumula diariamente.
              </p>
            </div>
          ) : null}
        </section>
      </div>
    </div>
  );
}

function Kpi({ label, value, success }: { label: string; value: string; success?: boolean }) {
  return (
    <div className="prosper-card p-4">
      <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">{label}</div>
      <div className={`text-2xl font-display font-extrabold font-mono mt-1 tabular-nums
                       ${success ? "text-success" : "text-fg"}`}>
        {value}
      </div>
    </div>
  );
}

function Row({ label, value, mono, small, success, badge }:
  { label: string; value: string; mono?: boolean; small?: boolean;
    success?: boolean; badge?: "success" | "warning" | "default" }) {
  return (
    <div className="contents">
      <dt className="text-fg-muted">{label}</dt>
      <dd className={`${mono || small ? "font-mono" : ""}
                     ${small ? "text-[10px]" : "text-xs"}
                     ${success ? "text-success font-bold" : "text-fg"} break-all`}>
        {badge ? <Badge tone={badge} size="sm">{value}</Badge> : value}
      </dd>
    </div>
  );
}
