"use client";
import Link from "next/link";
import { PageHeader, KpiCard, Badge } from "@prosper/ui";
import { RefreshButton } from "@/components/PageActions";
import { YieldChart } from "@/components/client/YieldChart";
import {
  ArrowDownToLine, ArrowUpFromLine, Coins, TrendingUp,
  Wallet, LineChart, CalendarClock, Hash,
} from "lucide-react";
import { useClientMe, useClientDashboard, fmtUsd } from "@/lib/client-portal";

const TX_LABEL: Record<string, string> = {
  subscribe: "Suscripción",
  redeem:    "Rescate",
  deposit:   "Carga (on-ramp)",
  withdraw:  "Retiro (off-ramp)",
  yield_accrual: "Yield acumulado",
};

const TX_TONE: Record<string, "success" | "warning" | "info" | "default"> = {
  subscribe: "info",
  redeem:    "warning",
  deposit:   "success",
  withdraw:  "default",
  yield_accrual: "success",
};

export default function ClientDashboardPage() {
  const { data: meData } = useClientMe();
  const { data, isLoading, mutate } = useClientDashboard();
  const canOperate = meData?.features?.can_operate ?? false;
  const kpis = data?.kpis;

  return (
    <div data-testid="client-dashboard">
      <PageHeader
        breadcrumbs={[{ label: "Client", href: "/client" }, { label: "Dashboard" }]}
        kicker={`Phase 7 · ${meData?.org?.commercial_name || meData?.org?.legal_name || "Tu portal"}`}
        title="Tu dashboard"
        subtitle="Posición, rendimiento y movimientos recientes en un solo lugar."
        actions={<RefreshButton onClick={() => mutate()} />}
      />

      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6" data-testid="kpi-row">
        <KpiCard
          label="Saldo USDC"
          value={kpis ? fmtUsd(kpis.available_usdc) : "—"}
          hint="Disponible para invertir o retirar"
        />
        <KpiCard
          label="Tokens Prosper"
          value={kpis ? `${kpis.token_balance.toFixed(2)} PUSD` : "—"}
          hint={kpis ? `≈ ${fmtUsd(kpis.token_value_usd)}` : "—"}
        />
        <KpiCard
          label="Principal invertido"
          value={kpis ? fmtUsd(kpis.principal_invested) : "—"}
          hint={`${data?.positions?.length || 0} posiciones activas`}
        />
        <KpiCard
          label="Yield acumulado"
          value={kpis ? fmtUsd(kpis.accrued_total) : "—"}
          hint={kpis ? `APR promedio ${kpis.avg_apr_pct.toFixed(2)}%` : "—"}
        />
      </div>

      {/* Action buttons (gated) */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-8" data-testid="action-row">
        <ActionBtn
          href="/client/onramp"
          icon={<ArrowDownToLine size={16} />}
          label="Cargar dinero"
          subtitle="USDC vía wire o crypto"
          disabled={!canOperate}
          testid="action-deposit"
        />
        <ActionBtn
          href="/client/investments"
          icon={<Coins size={16} />}
          label="Invertir"
          subtitle="Comprá Prosper Yield Token"
          disabled={!canOperate}
          testid="action-invest"
          primary
        />
        <ActionBtn
          href="/client/offramp"
          icon={<ArrowUpFromLine size={16} />}
          label="Retirar"
          subtitle="Off-ramp a tu cuenta"
          disabled={!canOperate}
          testid="action-withdraw"
        />
      </div>

      {/* Yield chart + Projection */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5 mb-6">
        <div className="prosper-card p-5 lg:col-span-2" data-testid="yield-card">
          <div className="flex items-center justify-between mb-3">
            <div>
              <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
                Rendimiento mensual
              </div>
              <h3 className="font-display font-bold text-lg text-fg flex items-center gap-1.5 mt-0.5">
                <LineChart size={14} className="text-success" /> Últimos 12 meses
              </h3>
            </div>
            {kpis && (
              <Badge tone="success" size="sm" data-testid="apr-badge">
                APR {kpis.avg_apr_pct.toFixed(2)}%
              </Badge>
            )}
          </div>
          {isLoading || !data ? (
            <div className="h-[220px] animate-pulse bg-bg-muted rounded" />
          ) : (
            <YieldChart data={data.monthly_yield} />
          )}
        </div>

        <div className="prosper-card p-5 space-y-4" data-testid="projection-card">
          <div>
            <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
              Proyección
            </div>
            <h3 className="font-display font-bold text-lg text-fg flex items-center gap-1.5 mt-0.5">
              <TrendingUp size={14} className="text-primary" /> Anualizado
            </h3>
          </div>

          <div className="space-y-3 text-sm">
            <Row label="Realizado YTD" value={data ? fmtUsd(data.projection.realized_ytd) : "—"} />
            <Row label="Proyectado anual" value={data ? fmtUsd(data.projection.projected_annual) : "—"} hint />
            <div className="h-px bg-border" />
            <Row
              label="Valor total cuenta"
              value={
                kpis
                  ? fmtUsd(kpis.available_usdc + kpis.token_value_usd + kpis.principal_invested + kpis.accrued_total)
                  : "—"
              }
              big
            />
          </div>
        </div>
      </div>

      {/* Positions + Recent tx */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-5">
        <section className="prosper-card p-5 lg:col-span-3" data-testid="positions-card">
          <div className="flex items-center justify-between mb-3">
            <div>
              <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
                Posiciones activas
              </div>
              <h3 className="font-display font-bold text-lg text-fg mt-0.5">
                Inversiones en curso
              </h3>
            </div>
            <Link
              href="/client/investments"
              className="text-[11px] font-mono uppercase tracking-wider text-primary hover:underline"
              data-testid="positions-see-all"
            >
              Ver todas →
            </Link>
          </div>

          {!data || data.positions.length === 0 ? (
            <EmptyHint
              icon={<Coins size={20} />}
              title="Sin posiciones activas"
              msg={canOperate
                ? "Hacé tu primera inversión para empezar a generar yield."
                : "Completá el onboarding para empezar a invertir."}
            />
          ) : (
            <div className="overflow-x-auto -mx-5">
              <table className="w-full text-sm" data-testid="positions-table">
                <thead>
                  <tr className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle border-b border-border">
                    <Th>Producto</Th>
                    <Th right>Principal</Th>
                    <Th right>APR</Th>
                    <Th right>Yield acum.</Th>
                    <Th>Madurez</Th>
                  </tr>
                </thead>
                <tbody>
                  {data.positions.slice(0, 6).map((p) => (
                    <tr key={p.position_id}
                        className="border-b border-border/60 hover:bg-surface-hover"
                        data-testid={`position-${p.position_id}`}>
                      <Td>{p.product}</Td>
                      <Td right>{fmtUsd(p.principal)}</Td>
                      <Td right>
                        <span className="text-success">{p.apr_pct.toFixed(2)}%</span>
                      </Td>
                      <Td right>{fmtUsd(p.accrued)}</Td>
                      <Td>
                        <span className="inline-flex items-center gap-1 text-fg-muted text-xs">
                          <CalendarClock size={11} />
                          {p.days_to_maturity != null ? `${p.days_to_maturity}d` : "—"}
                        </span>
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="prosper-card p-5 lg:col-span-2" data-testid="recent-tx-card">
          <div className="flex items-center justify-between mb-3">
            <div>
              <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
                Últimos movimientos
              </div>
              <h3 className="font-display font-bold text-lg text-fg mt-0.5">Transacciones</h3>
            </div>
            <Link
              href="/client/transactions"
              className="text-[11px] font-mono uppercase tracking-wider text-primary hover:underline"
              data-testid="tx-see-all"
            >
              Historial →
            </Link>
          </div>
          {!data || data.recent_transactions.length === 0 ? (
            <EmptyHint
              icon={<Wallet size={20} />}
              title="Sin movimientos aún"
              msg="Tus cargas, inversiones y rescates aparecerán acá."
            />
          ) : (
            <ul className="space-y-2" data-testid="recent-tx-list">
              {data.recent_transactions.map((t) => (
                <li
                  key={t.tx_id}
                  className="flex items-center gap-3 py-2 border-b border-border/50 last:border-0"
                  data-testid={`tx-${t.tx_id}`}
                >
                  <div className="shrink-0 h-8 w-8 rounded-full bg-surface flex items-center justify-center">
                    <Hash size={12} className="text-fg-subtle" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-fg truncate">
                        {TX_LABEL[t.type] || t.type}
                      </span>
                      <Badge tone={TX_TONE[t.type] || "default"} size="sm">{t.status}</Badge>
                    </div>
                    <div className="text-[10px] font-mono text-fg-subtle">
                      {new Date(t.created_at).toLocaleString()}
                    </div>
                  </div>
                  <div className="text-sm font-mono text-fg shrink-0">{fmtUsd(t.amount)}</div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return (
    <th className={`px-5 py-2 ${right ? "text-right" : "text-left"} font-normal`}>{children}</th>
  );
}
function Td({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return (
    <td className={`px-5 py-2 ${right ? "text-right font-mono" : "text-left"}`}>{children}</td>
  );
}

function Row({ label, value, hint, big }:
  { label: string; value: string; hint?: boolean; big?: boolean }) {
  return (
    <div className="flex items-baseline justify-between">
      <span className={`text-fg-muted ${big ? "text-sm" : "text-xs"}`}>{label}</span>
      <span className={`font-mono ${big ? "text-lg font-bold text-fg" : hint ? "text-fg-muted" : "text-fg"}`}>
        {value}
      </span>
    </div>
  );
}

function EmptyHint({ icon, title, msg }:
  { icon: React.ReactNode; title: string; msg: string }) {
  return (
    <div className="py-10 text-center text-fg-subtle">
      <div className="mx-auto mb-2 h-10 w-10 rounded-full bg-surface flex items-center justify-center">
        {icon}
      </div>
      <div className="text-sm font-display font-semibold text-fg">{title}</div>
      <div className="text-xs mt-1 max-w-xs mx-auto">{msg}</div>
    </div>
  );
}

function ActionBtn({ href, icon, label, subtitle, disabled, testid, primary }:
  { href: string; icon: React.ReactNode; label: string; subtitle: string;
    disabled?: boolean; testid: string; primary?: boolean }) {
  const base = `flex items-center gap-3 p-4 rounded-xl border transition-all
                ${disabled
                  ? "opacity-40 cursor-not-allowed bg-surface border-border"
                  : primary
                    ? "bg-primary text-white border-primary hover:bg-primary/90 shadow-sm"
                    : "bg-surface border-border hover:border-primary/40 hover:bg-surface-hover"}`;

  const content = (
    <>
      <div className={`shrink-0 h-9 w-9 rounded-full flex items-center justify-center
                       ${primary && !disabled ? "bg-white/15" : "bg-primary/10 text-primary"}`}>
        {icon}
      </div>
      <div className="flex-1 min-w-0">
        <div className={`text-sm font-display font-bold ${primary && !disabled ? "text-white" : "text-fg"}`}>
          {label}
        </div>
        <div className={`text-[11px] ${primary && !disabled ? "text-white/70" : "text-fg-muted"}`}>
          {disabled ? "Disponible al aprobar KYB" : subtitle}
        </div>
      </div>
    </>
  );

  if (disabled) {
    return (
      <div
        title="Disponible al aprobar KYB"
        className={base}
        data-testid={testid}
        data-disabled="true"
        aria-disabled="true"
      >
        {content}
      </div>
    );
  }
  return (
    <Link href={href} className={base} data-testid={testid}>
      {content}
    </Link>
  );
}
