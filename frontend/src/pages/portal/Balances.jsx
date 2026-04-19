import { useEffect, useState } from "react";
import api from "@/lib/api";
import { useApp } from "@/contexts/AppContext";
import { PageHeader, MetricBar, MetricCell, StatusBadge, EmptyState, CopyField } from "@/components/common";
import { fmtMoney, fmtNum, fmtDate } from "@/lib/format";

export default function PortalBalances() {
  const [positions, setPositions] = useState([]);
  useEffect(() => { api.get("/positions").then(({ data }) => setPositions(data.items || [])); }, []);

  const principal = positions.reduce((s, p) => s + (p.principal || 0), 0);
  const accrued = positions.reduce((s, p) => s + (p.accrued_interest || 0), 0);
  const claimed = positions.reduce((s, p) => s + (p.claimed_interest || 0), 0);

  return (
    <div data-testid="portal-balances">
      <PageHeader title="Balances & Positions" />
      <MetricBar>
        <MetricCell label="Total Principal" value={fmtMoney(principal)} />
        <MetricCell label="Accrued Yield" value={fmtMoney(accrued)} />
        <MetricCell label="Claimed Yield" value={fmtMoney(claimed)} />
        <MetricCell label="Positions" value={positions.length} />
      </MetricBar>
      <div className="mt-6">
        {positions.length === 0 ? <EmptyState title="No positions held" /> : (
          <div className="prosper-card overflow-hidden">
            <table className="data-table w-full">
              <thead><tr>
                <th className="text-left px-4 py-3">Stellar Address</th>
                <th className="text-right px-4 py-3">Principal</th>
                <th className="text-right px-4 py-3">Accrued</th>
                <th className="text-left px-4 py-3">Maturity</th>
                <th className="text-left px-4 py-3">Status</th>
              </tr></thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.position_id} data-testid={`pos-${p.position_id}`}>
                    <td className="px-4 py-3"><CopyField value={p.stellar_address} /></td>
                    <td className="px-4 py-3 text-right font-mono">{fmtMoney(p.principal)}</td>
                    <td className="px-4 py-3 text-right font-mono text-[var(--success)]">{fmtMoney(p.accrued_interest)}</td>
                    <td className="px-4 py-3 text-xs font-mono text-[var(--fg-muted)]">{fmtDate(p.maturity_date)}</td>
                    <td className="px-4 py-3"><StatusBadge value={p.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
