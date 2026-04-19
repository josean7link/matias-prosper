import { useEffect, useState } from "react";
import api from "@/lib/api";
import { PageHeader, StatusBadge, EmptyState } from "@/components/common";
import { fmtMoney, fmtDate } from "@/lib/format";

export default function EndCustomers() {
  const [items, setItems] = useState([]);
  useEffect(() => { api.get("/end-customers").then(({ data }) => setItems(data.items || [])); }, []);

  return (
    <div data-testid="portal-end-customers">
      <PageHeader title="End Customers" subtitle={`${items.length} downstream customers`} />
      {items.length === 0 ? <EmptyState title="No end customers registered yet" /> : (
        <div className="prosper-card overflow-hidden">
          <table className="data-table w-full">
            <thead><tr>
              <th className="text-left px-4 py-3">External Ref</th>
              <th className="text-left px-4 py-3">Name</th>
              <th className="text-left px-4 py-3">Email</th>
              <th className="text-left px-4 py-3">Country</th>
              <th className="text-right px-4 py-3">Invested</th>
              <th className="text-left px-4 py-3">KYC</th>
            </tr></thead>
            <tbody>
              {items.map((c) => (
                <tr key={c.end_customer_id} data-testid={`ec-${c.end_customer_id}`}>
                  <td className="px-4 py-3 font-mono text-xs">{c.external_ref}</td>
                  <td className="px-4 py-3 text-white">{c.name}</td>
                  <td className="px-4 py-3 text-xs font-mono text-[#ccc]">{c.email}</td>
                  <td className="px-4 py-3 font-mono text-[#888]">{c.country}</td>
                  <td className="px-4 py-3 text-right font-mono">{fmtMoney(c.total_invested)}</td>
                  <td className="px-4 py-3"><StatusBadge value={c.kyc_status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
