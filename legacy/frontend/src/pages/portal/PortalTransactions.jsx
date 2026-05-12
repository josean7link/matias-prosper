import { useEffect, useState } from "react";
import api from "@/lib/api";
import { useApp } from "@/contexts/AppContext";
import { PageHeader, StatusBadge, StellarLink, CopyField, EmptyState } from "@/components/common";
import { fmtMoney, fmtDateTime } from "@/lib/format";

export default function PortalTransactions() {
  const { env } = useApp();
  const [items, setItems] = useState([]);
  useEffect(() => { api.get(`/transactions?env=${env}&limit=100`).then(({ data }) => setItems(data.items || [])); }, [env]);

  return (
    <div data-testid="portal-transactions">
      <PageHeader title="Transactions" />
      {items.length === 0 ? <EmptyState title="No transactions yet" /> : (
        <div className="prosper-card overflow-x-auto">
          <table className="data-table w-full">
            <thead><tr>
              <th className="text-left px-4 py-3">When</th>
              <th className="text-left px-4 py-3">Type</th>
              <th className="text-right px-4 py-3">Amount</th>
              <th className="text-left px-4 py-3">Asset</th>
              <th className="text-left px-4 py-3">prosperTxId</th>
              <th className="text-left px-4 py-3">Hash</th>
              <th className="text-left px-4 py-3">Status</th>
            </tr></thead>
            <tbody>
              {items.map((t) => (
                <tr key={t.tx_id} data-testid={`ptx-${t.tx_id}`}>
                  <td className="px-4 py-3 font-mono text-xs text-[var(--fg-muted)]">{fmtDateTime(t.created_at)}</td>
                  <td className="px-4 py-3 text-xs uppercase tracking-wider">{t.type}</td>
                  <td className="px-4 py-3 text-right font-mono">{fmtMoney(t.amount, "USD", 2)}</td>
                  <td className="px-4 py-3 font-mono">{t.asset_code}</td>
                  <td className="px-4 py-3"><CopyField value={t.prosper_tx_id} /></td>
                  <td className="px-4 py-3"><StellarLink hash={t.tx_hash} /></td>
                  <td className="px-4 py-3"><StatusBadge value={t.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
