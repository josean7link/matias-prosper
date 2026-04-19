import { useEffect, useState } from "react";
import api from "@/lib/api";
import { useApp } from "@/contexts/AppContext";
import { PageHeader, KpiCard } from "@/components/common";
import { fmtMoney, fmtBps, fmtNum } from "@/lib/format";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";

export default function Yield() {
  const { env } = useApp();
  const [overview, setOverview] = useState(null);
  const [positions, setPositions] = useState([]);
  const [products, setProducts] = useState([]);

  useEffect(() => {
    api.get(`/dashboard/overview?env=${env}`).then(({ data }) => setOverview(data));
    api.get("/positions").then(({ data }) => setPositions(data.items || []));
    api.get("/products").then(({ data }) => setProducts(data.items || []));
  }, [env]);

  const accrued = positions.reduce((s, p) => s + (p.accrued_interest || 0), 0);
  const principal = positions.reduce((s, p) => s + (p.principal || 0), 0);
  const avgApr = positions.length > 0 && products.length > 0
    ? positions.reduce((s, p) => {
        const prod = products.find(pr => pr.product_id === p.product_id);
        return s + (prod?.apr_bps || 0);
      }, 0) / positions.length
    : 0;

  return (
    <div data-testid="portal-yield">
      <PageHeader title="Yield & Performance" />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <KpiCard label="Total Accrued" value={fmtMoney(accrued)} testId="yield-accrued" />
        <KpiCard label="Principal" value={fmtMoney(principal)} testId="yield-principal" />
        <KpiCard label="Average APR" value={fmtBps(avgApr)} testId="yield-apr" />
        <KpiCard label="Yield Paid (platform · 30d)" value={fmtMoney(overview?.kpis?.yield_paid_30d || 0)} testId="yield-30d" />
      </div>
      <div className="prosper-card p-5">
        <div className="text-[10px] uppercase tracking-wider text-[#888] mb-3">Fund NAV performance</div>
        <div className="h-[300px]">
          <ResponsiveContainer>
            <LineChart data={overview?.nav_series || []}>
              <CartesianGrid stroke="#1a1a1a" vertical={false} />
              <XAxis dataKey="as_of" stroke="#555" fontSize={10} tickFormatter={(v) => v.slice(5,10)} />
              <YAxis stroke="#555" fontSize={10} tickFormatter={(v) => v.toFixed(4)} domain={["auto", "auto"]} />
              <Tooltip contentStyle={{ background: "#0a0a0a", border: "1px solid #222", fontSize: 12 }} formatter={(v) => fmtNum(v, 6)} />
              <Line type="monotone" dataKey="nav" stroke="#00C853" strokeWidth={1.5} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
