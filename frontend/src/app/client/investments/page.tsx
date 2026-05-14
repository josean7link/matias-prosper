"use client";
import Link from "next/link";
import { Coins, Plus, Lock, Sparkles, ArrowRight } from "lucide-react";
import { PageHeader, Badge } from "@prosper/ui";
import { RefreshButton } from "@/components/PageActions";
import { useClientMe } from "@/lib/client-portal";
import { fmtCur } from "@/lib/alfred";
import { usePositions, fmtPct, type Position } from "@/lib/invest";

const STATUS_TONE = {
  active:   "success",
  matured:  "warning",
  redeemed: "default",
} as const;

export default function InvestmentsPage() {
  const { data: me } = useClientMe();
  const { data, isLoading, mutate } = usePositions();
  const positions = data?.items ?? [];
  const canOperate = me?.features?.can_operate ?? false;

  const totalPrincipal = positions
    .filter((p) => p.status === "active")
    .reduce((s, p) => s + p.principal_usd, 0);
  const totalAccrued = positions.reduce((s, p) => s + (p.accrued_interest || 0), 0);

  return (
    <div data-testid="investments-page">
      <PageHeader
        breadcrumbs={[{ label: "Client", href: "/client" }, { label: "Inversiones" }]}
        kicker="Phase 9 · Tus posiciones"
        title="Inversiones"
        subtitle="Todas tus posiciones activas, maduradas y redimidas."
        actions={
          <div className="flex items-center gap-2">
            <RefreshButton onClick={() => mutate()} />
            <Link
              href="/client/invest"
              className={`prosper-btn-primary h-9 px-3 text-xs gap-1.5
                          ${!canOperate ? "opacity-40 pointer-events-none" : ""}`}
              data-testid="invest-new"
            >
              <Plus size={13} /> Nueva inversión
            </Link>
          </div>
        }
      />

      {/* Summary KPIs */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 mb-6">
        <Kpi label="Posiciones activas"
             value={String(positions.filter((p) => p.status === "active").length)} />
        <Kpi label="Principal total"  value={fmtCur(totalPrincipal, "USDC")} />
        <Kpi label="Yield acumulado"  value={fmtCur(totalAccrued, "USDC")} success />
      </div>

      {isLoading ? (
        <div className="prosper-card p-8 animate-pulse h-32" />
      ) : positions.length === 0 ? (
        <div className="prosper-card p-10 text-center" data-testid="positions-empty">
          <Coins size={28} className="mx-auto text-fg-subtle mb-2" />
          <h2 className="font-display font-bold text-lg text-fg">Sin posiciones todavía</h2>
          <p className="text-sm text-fg-muted mt-2 max-w-sm mx-auto">
            Hacé tu primera carga o invertí USDC libre para empezar a generar yield.
          </p>
          {canOperate && (
            <Link href="/client/invest"
              className="prosper-btn-primary inline-flex h-10 px-5 mt-4 text-sm gap-2">
              <Plus size={14}/> Invertir ahora
            </Link>
          )}
        </div>
      ) : (
        <div className="space-y-3" data-testid="positions-list">
          {positions.map((p) => <PositionRow key={p.position_id} pos={p} />)}
        </div>
      )}
    </div>
  );
}

function PositionRow({ pos }: { pos: Position }) {
  const daysToMaturity = pos.maturity
    ? Math.max(0, Math.ceil((new Date(pos.maturity).getTime() - Date.now()) / 86400_000))
    : null;

  return (
    <Link
      href={`/client/investments/${pos.position_id}`}
      className="prosper-card p-5 flex items-center gap-4 hover:border-primary/40 transition-colors"
      data-testid={`pos-${pos.position_id}`}
    >
      <div className={`h-10 w-10 rounded-full flex items-center justify-center
                       ${pos.maturity ? "bg-primary/10 text-primary"
                                      : "bg-success/10 text-success"}`}>
        {pos.maturity ? <Lock size={16} /> : <Sparkles size={16} />}
      </div>

      <div className="flex-1 grid grid-cols-2 sm:grid-cols-5 gap-2 sm:gap-4">
        <Cell label="Producto" value={pos.product_id} mono />
        <Cell label="Principal" value={fmtCur(pos.principal_usd, "USDC")} />
        <Cell label="APR" value={fmtPct(pos.apr_bps)} success />
        <Cell label="Accrued" value={fmtCur(pos.accrued_interest || 0, "USDC")} />
        <Cell label="Maturity"
              value={daysToMaturity != null ? `${daysToMaturity}d` : "Liquid"} />
      </div>

      <div className="hidden sm:block">
        <Badge tone={STATUS_TONE[pos.status] || "default"} size="sm">{pos.status}</Badge>
      </div>
      <ArrowRight size={14} className="text-fg-subtle" />
    </Link>
  );
}

function Kpi({ label, value, success }: { label: string; value: string; success?: boolean }) {
  return (
    <div className="prosper-card p-4">
      <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">{label}</div>
      <div className={`text-xl font-display font-extrabold font-mono mt-1 tabular-nums
                       ${success ? "text-success" : "text-fg"}`}>
        {value}
      </div>
    </div>
  );
}

function Cell({ label, value, mono, success }:
  { label: string; value: string; mono?: boolean; success?: boolean }) {
  return (
    <div>
      <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">{label}</div>
      <div className={`text-sm ${mono ? "font-mono" : ""}
                      ${success ? "text-success font-bold" : "text-fg"} tabular-nums`}>
        {value}
      </div>
    </div>
  );
}
