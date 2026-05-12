import { useEffect, useState } from "react";
import api from "@/lib/api";
import { useApp } from "@/contexts/AppContext";
import { PageHeader, KpiCard, StatusBadge, EmptyState } from "@/components/common";
import { fmtMoney, fmtDate, fmtNum, fmtBps } from "@/lib/format";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";

export default function PortalOverview() {
  const { env } = useApp();
  const [overview, setOverview] = useState(null);
  const [positions, setPositions] = useState([]);
  const [txs, setTxs] = useState([]);

  useEffect(() => {
    api.get(`/dashboard/overview?env=${env}`).then(({ data }) => setOverview(data));
    api.get("/positions").then(({ data }) => setPositions(data.items || []));
    api.get("/transactions?limit=10").then(({ data }) => setTxs(data.items || []));
  }, [env]);

  const totalPrincipal = positions.reduce((s, p) => s + (p.principal || 0), 0);
  const totalAccrued = positions.reduce((s, p) => s + (p.accrued_interest || 0), 0);

  return (
    <div data-testid="portal-overview">
      <PageHeader title="My Portfolio" subtitle="Welcome to your Prosper dashboard" />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <KpiCard label="Principal Invested" value={fmtMoney(totalPrincipal)} testId="kpi-principal" />
        <KpiCard label="Accrued Yield" value={fmtMoney(totalAccrued)} sublabel="unclaimed" testId="kpi-accrued" />
        <KpiCard label="Active Positions" value={fmtNum(positions.filter(p => p.status === "active").length, 0)} testId="kpi-positions" />
        <KpiCard label="Fund NAV" value={overview?.nav_series?.length ? fmtNum(overview.nav_series[overview.nav_series.length-1].nav, 6) : "—"} testId="kpi-nav" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        <div className="lg:col-span-2 prosper-card p-5">
          <div className="text-[10px] uppercase tracking-wider text-[var(--fg-muted)] mb-3">NAV · 14 days</div>
          <div className="h-[240px]">
            <ResponsiveContainer>
              <AreaChart data={overview?.nav_series || []}>
                <defs><linearGradient id="pnav" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#00C853" stopOpacity={0.4}/><stop offset="100%" stopColor="#00C853" stopOpacity={0}/></linearGradient></defs>
                <CartesianGrid stroke="var(--border)" vertical={false} />
                <XAxis dataKey="as_of" stroke="var(--fg-muted)" fontSize={10} tickFormatter={(v) => v.slice(5,10)} />
                <YAxis stroke="var(--fg-muted)" fontSize={10} tickFormatter={(v) => v.toFixed(4)} domain={["auto","auto"]} />
                <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", color: "var(--fg)", borderRadius: "8px", fontSize: 12 }} formatter={(v) => fmtNum(v, 6)} />
                <Area type="monotone" dataKey="nav" stroke="#00C853" strokeWidth={1.5} fill="url(#pnav)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="prosper-card p-5">
          <div className="text-[10px] uppercase tracking-wider text-[var(--fg-muted)] mb-3">Recent Transactions</div>
          {txs.length === 0 ? <EmptyState title="No activity yet" /> : (
            <div className="space-y-2">
              {txs.slice(0, 6).map(t => (
                <div key={t.tx_id} className="flex justify-between items-center py-2 border-b border-[var(--border)] last:border-0">
                  <div>
                    <div className="text-sm capitalize">{t.type}</div>
                    <div className="text-xs font-mono text-[var(--fg-subtle)]">{fmtDate(t.created_at, true)}</div>
                  </div>
                  <div className="text-right">
                    <div className="font-mono text-sm">{fmtMoney(t.amount, "USD", 2)}</div>
                    <StatusBadge value={t.status} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
