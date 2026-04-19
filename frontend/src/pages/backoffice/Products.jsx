import { useEffect, useState } from "react";
import api from "@/lib/api";
import { PageHeader, StatusBadge, EmptyState } from "@/components/common";
import { fmtBps, fmtMoney } from "@/lib/format";

export default function Products() {
  const [items, setItems] = useState([]);
  useEffect(() => { api.get("/products").then(({ data }) => setItems(data.items || [])); }, []);

  return (
    <div data-testid="products-page">
      <PageHeader title="Products" subtitle="Term staking and liquid yield products" />
      {items.length === 0 ? <EmptyState title="No products defined" /> : (
        <div className="prosper-card overflow-hidden">
          <table className="data-table w-full">
            <thead><tr>
              <th className="text-left px-4 py-3">Name</th>
              <th className="text-left px-4 py-3">Kind</th>
              <th className="text-right px-4 py-3">Term</th>
              <th className="text-right px-4 py-3">APR</th>
              <th className="text-right px-4 py-3">Min Amount</th>
              <th className="text-left px-4 py-3">Principal / Payout</th>
              <th className="text-left px-4 py-3">Status</th>
            </tr></thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.product_id} data-testid={`product-row-${p.product_id}`}>
                  <td className="px-4 py-3 text-white font-medium">{p.name}</td>
                  <td className="px-4 py-3 text-[#ccc] capitalize">{p.kind.replace("_", " ")}</td>
                  <td className="px-4 py-3 text-right font-mono">{p.term_days ? `${p.term_days}d` : "—"}</td>
                  <td className="px-4 py-3 text-right font-mono text-[#00C853]">{fmtBps(p.apr_bps)}</td>
                  <td className="px-4 py-3 text-right font-mono">{fmtMoney(p.min_amount)}</td>
                  <td className="px-4 py-3 font-mono text-xs text-[#ccc]">{p.principal_asset} → {p.payout_asset}</td>
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
