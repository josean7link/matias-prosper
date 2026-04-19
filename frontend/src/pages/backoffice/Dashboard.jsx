import { useEffect, useState } from "react";
import { useApp } from "@/contexts/AppContext";
import api from "@/lib/api";
import { PageHeader, KpiCard } from "@/components/common";
import { fmtMoney, fmtCompact, fmtNum } from "@/lib/format";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, BarChart, Bar, CartesianGrid } from "recharts";

export default function Dashboard() {
  const { env } = useApp();
  const [data, setData] = useState(null);

  useEffect(() => {
    api.get(`/dashboard/overview?env=${env}`).then(({ data }) => setData(data)).catch(() => setData({ error: true }));
  }, [env]);

  if (!data) return <div className="text-[#888] font-mono text-sm">Loading control room…</div>;
  const k = data.kpis || {};

  return (
    <div data-testid="dashboard-page">
      <PageHeader
        title="Control Room"
        subtitle={`Global operational view · ${env.toUpperCase()}`}
      />

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3 mb-6">
        <KpiCard label="AUM (USD)" value={fmtMoney(k.aum_usd || 0, "USD", 0)} sublabel={`Across ${k.active_orgs} orgs`} testId="kpi-aum" />
        <KpiCard label="PROS Circulating" value={fmtCompact(k.circulating_supply || 0)} sublabel={`of ${fmtCompact(k.total_supply || 0)} total`} testId="kpi-supply" />
        <KpiCard label="Active Investors" value={fmtNum(k.active_investors || 0, 0)} sublabel="Across all partners" testId="kpi-investors" />
        <KpiCard label="Tx · 24h" value={fmtNum(k.tx_24h || 0, 0)} sublabel="Processed transactions" testId="kpi-tx" />
        <KpiCard label="Yield Paid · 30d" value={fmtMoney(k.yield_paid_30d || 0)} sublabel="Claim volume" testId="kpi-yield" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 mb-6">
        <div className="lg:col-span-2 prosper-card p-5">
          <div className="flex items-start justify-between mb-4">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-[#888]">NAV per token · {data.primary_fund_code}</div>
              <div className="font-mono text-2xl text-white mt-1">
                {data.nav_series?.length ? fmtNum(data.nav_series[data.nav_series.length - 1].nav, 6) : "—"}
              </div>
            </div>
            <div className="text-[10px] font-mono uppercase text-[#888]">14 days</div>
          </div>
          <div className="h-[220px]">
            <ResponsiveContainer>
              <AreaChart data={data.nav_series || []}>
                <defs>
                  <linearGradient id="navGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#0066FF" stopOpacity={0.5} />
                    <stop offset="100%" stopColor="#0066FF" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#1a1a1a" vertical={false} />
                <XAxis dataKey="as_of" stroke="#555" fontSize={10} tickFormatter={(v) => v.slice(5, 10)} />
                <YAxis stroke="#555" fontSize={10} tickFormatter={(v) => v.toFixed(4)} domain={["auto", "auto"]} />
                <Tooltip contentStyle={{ background: "#0a0a0a", border: "1px solid #222", fontSize: 12 }}
                         labelStyle={{ color: "#888" }} formatter={(v) => fmtNum(v, 6)} />
                <Area type="monotone" dataKey="nav" stroke="#0066FF" strokeWidth={1.5} fill="url(#navGrad)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="prosper-card p-5">
          <div className="text-[10px] uppercase tracking-wider text-[#888] mb-4">Ops Queue</div>
          <div className="space-y-3">
            <QueueItem label="Open Onboarding" value={k.open_onboarding || 0} tone="warning" />
            <QueueItem label="Pending Reconciliation" value={k.pending_reconciliation || 0} tone="warning" />
            <QueueItem label="Open Alerts" value={k.open_alerts || 0} tone="critical" />
            <QueueItem label="Active Orgs" value={k.active_orgs || 0} tone="success" />
          </div>
        </div>
      </div>

      <div className="prosper-card p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="text-[10px] uppercase tracking-wider text-[#888]">Transaction Volume · 14d</div>
        </div>
        <div className="h-[220px]">
          <ResponsiveContainer>
            <BarChart data={data.volume_series || []}>
              <CartesianGrid stroke="#1a1a1a" vertical={false} />
              <XAxis dataKey="date" stroke="#555" fontSize={10} tickFormatter={(v) => v.slice(5)} />
              <YAxis stroke="#555" fontSize={10} tickFormatter={(v) => fmtCompact(v)} />
              <Tooltip contentStyle={{ background: "#0a0a0a", border: "1px solid #222", fontSize: 12 }}
                       formatter={(v) => fmtMoney(v)} />
              <Bar dataKey="volume" fill="#0066FF" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}

const QueueItem = ({ label, value, tone }) => {
  const colorMap = { warning: "#FFAB00", critical: "#FF3D00", success: "#00C853" };
  return (
    <div className="flex items-center justify-between py-2 border-b border-[#1a1a1a] last:border-0">
      <div className="text-sm text-[#ccc]">{label}</div>
      <div className="flex items-center gap-2">
        <span className="status-dot" style={{ background: colorMap[tone] }} />
        <span className="font-mono text-lg tabular-nums">{value}</span>
      </div>
    </div>
  );
};
