import { useEffect, useState } from "react";
import api from "@/lib/api";
import { PageHeader, StatusBadge, CopyField, EmptyState } from "@/components/common";
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
      <PageHeader title="Positions Explorer" subtitle={`${items.length} active positions`} />
      <div className="mb-4">
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger className="w-[200px] bg-[#0a0a0a] border-[#1a1a1a] rounded-sm" data-testid="positions-filter-status">
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
                  <td className="px-4 py-3 font-mono text-xs text-[#ccc]">{p.user_reference_id}</td>
                  <td className="px-4 py-3"><CopyField value={p.stellar_address} testId={`addr-${p.position_id}`} /></td>
                  <td className="px-4 py-3 text-right font-mono">{fmtMoney(p.principal)}</td>
                  <td className="px-4 py-3 text-right font-mono text-[#00C853]">{fmtMoney(p.accrued_interest)}</td>
                  <td className="px-4 py-3 text-right font-mono">{fmtMoney(p.claimed_interest)}</td>
                  <td className="px-4 py-3 text-xs font-mono text-[#888]">{fmtDate(p.start_date)}</td>
                  <td className="px-4 py-3 text-xs font-mono text-[#888]">{fmtDate(p.maturity_date)}</td>
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
