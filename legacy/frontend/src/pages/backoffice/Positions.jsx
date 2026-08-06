import { useEffect, useState } from "react";
import api from "@/lib/api";
import { PageHeader, StatusBadge, CopyField, EmptyState } from "@/components/common";
import ExportButton from "@/components/ExportButton";
import { fmtMoney, fmtDate, fmtNum } from "@/lib/format";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export default function Positions() {
  const [items, setItems] = useState([]);
  const [status, setStatus] = useState("all");

  useEffect(() => {
    const params = new URLSearchParams();
    if (status !== "all") params.set("status", status);
    api.get(`/positions?${params}`).then(({ data }) => setItems(data.items || []));
  }, [status]);

  return (
    <div data-testid="positions-page">
      <PageHeader title="Positions Explorer" subtitle={`${items.length} active positions`}
        actions={
          <ExportButton filename={`positions_${new Date().toISOString().slice(0,10)}`}
                        rows={items.map(p => ({
                          position_id: p.position_id, org_id: p.org_id,
                          user_ref: p.user_reference_id, product_id: p.product_id,
                          principal: p.principal, accrued: p.accrued_interest,
                          claimed: p.claimed_interest, stellar_address: p.stellar_address,
                          start: p.start_date, maturity: p.maturity_date, status: p.status,
                        }))}
                        testId="positions-export" />
        }
      />
      <div className="mb-4">
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger className="w-[200px] bg-[var(--surface)] border-[var(--border)] rounded-md" data-testid="positions-filter-status">
            <SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            <SelectItem value="active">Active</SelectItem>
            <SelectItem value="pending">Pending</SelectItem>
            <SelectItem value="matured">Matured</SelectItem>
            <SelectItem value="redeemed">Redeemed</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {items.length === 0 ? <EmptyState title="No positions" /> : (
        <div className="prosper-card overflow-hidden">
          <table className="data-table w-full">
            <thead><tr>
              <th className="text-left px-4 py-3">Position ID</th>
              <th className="text-left px-4 py-3">User Ref</th>
              <th className="text-left px-4 py-3">Stellar Address</th>
              <th className="text-right px-4 py-3">Principal</th>
              <th className="text-right px-4 py-3">Accrued</th>
              <th className="text-right px-4 py-3">Claimed</th>
              <th className="text-left px-4 py-3">Start</th>
              <th className="text-left px-4 py-3">Maturity</th>
              <th className="text-left px-4 py-3">Status</th>
            </tr></thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.position_id} data-testid={`position-row-${p.position_id}`}>
                  <td className="px-4 py-3 font-mono text-xs">{p.position_id.slice(0, 16)}…</td>
                  <td className="px-4 py-3 font-mono text-xs text-[var(--fg)]">{p.user_reference_id}</td>
                  <td className="px-4 py-3"><CopyField value={p.stellar_address} testId={`addr-${p.position_id}`} /></td>
                  <td className="px-4 py-3 text-right font-mono">{fmtMoney(p.principal)}</td>
                  <td className="px-4 py-3 text-right font-mono text-[var(--success)]">{fmtMoney(p.accrued_interest)}</td>
                  <td className="px-4 py-3 text-right font-mono">{fmtMoney(p.claimed_interest)}</td>
                  <td className="px-4 py-3 text-xs font-mono text-[var(--fg-muted)]">{fmtDate(p.start_date)}</td>
                  <td className="px-4 py-3 text-xs font-mono text-[var(--fg-muted)]">{fmtDate(p.maturity_date)}</td>
                  <td className="px-4 py-3"><StatusBadge value={p.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
