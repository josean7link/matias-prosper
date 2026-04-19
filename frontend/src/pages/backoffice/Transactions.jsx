import { useEffect, useState } from "react";
import api from "@/lib/api";
import { useApp } from "@/contexts/AppContext";
import { PageHeader, StatusBadge, StellarLink, CopyField, EmptyState } from "@/components/common";
import { fmtMoney, fmtDateTime } from "@/lib/format";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export default function Transactions() {
  const { env } = useApp();
  const [items, setItems] = useState([]);
  const [search, setSearch] = useState("");
  const [type, setType] = useState("all");
  const [status, setStatus] = useState("all");

  useEffect(() => {
    const params = new URLSearchParams({ env });
    if (search) params.set("search", search);
    if (type !== "all") params.set("type", type);
    if (status !== "all") params.set("status", status);
    api.get(`/transactions?${params}`).then(({ data }) => setItems(data.items || []));
  }, [search, type, status, env]);

  return (
    <div data-testid="transactions-page">
      <PageHeader title="Transactions Ledger" subtitle={`${items.length} transactions · ${env}`} />
      <div className="flex gap-3 mb-4">
        <Input placeholder="Search hash, prosperTxId, memo…"
               className="max-w-sm bg-[var(--surface)] border-[var(--border)] rounded-md font-mono text-xs"
               value={search} onChange={(e) => setSearch(e.target.value)} data-testid="tx-search" />
        <Select value={type} onValueChange={setType}>
          <SelectTrigger className="w-[160px] bg-[var(--surface)] border-[var(--border)] rounded-md"><SelectValue placeholder="Type" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All types</SelectItem>
            {["mint", "burn", "subscribe", "redeem", "transfer", "deposit", "withdraw", "claim", "fund", "fee"].map(t =>
              <SelectItem key={t} value={t}>{t}</SelectItem>
            )}
          </SelectContent>
        </Select>
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger className="w-[160px] bg-[var(--surface)] border-[var(--border)] rounded-md"><SelectValue placeholder="Status" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All</SelectItem>
            {["pending", "submitted", "confirmed", "failed", "retrying"].map(s =>
              <SelectItem key={s} value={s}>{s}</SelectItem>
            )}
          </SelectContent>
        </Select>
      </div>
      {items.length === 0 ? <EmptyState title="No transactions match" /> : (
        <div className="prosper-card overflow-x-auto">
          <table className="data-table w-full">
            <thead><tr>
              <th className="text-left px-4 py-3">When</th>
              <th className="text-left px-4 py-3">Type</th>
              <th className="text-right px-4 py-3">Amount</th>
              <th className="text-left px-4 py-3">Asset</th>
              <th className="text-left px-4 py-3">prosperTxId</th>
              <th className="text-left px-4 py-3">Tx Hash</th>
              <th className="text-right px-4 py-3">Ledger</th>
              <th className="text-left px-4 py-3">Status</th>
            </tr></thead>
            <tbody>
              {items.map((t) => (
                <tr key={t.tx_id} data-testid={`tx-row-${t.tx_id}`}>
                  <td className="px-4 py-3 font-mono text-xs text-[var(--fg-muted)]">{fmtDateTime(t.created_at)}</td>
                  <td className="px-4 py-3"><span className="uppercase text-xs font-semibold tracking-wider">{t.type}</span></td>
                  <td className="px-4 py-3 text-right font-mono">{fmtMoney(t.amount, "USD", 2)}</td>
                  <td className="px-4 py-3 font-mono text-[var(--fg)]">{t.asset_code}</td>
                  <td className="px-4 py-3"><CopyField value={t.prosper_tx_id} testId={`ptxid-${t.tx_id}`} /></td>
                  <td className="px-4 py-3"><StellarLink hash={t.tx_hash} testId={`txhash-${t.tx_id}`} /></td>
                  <td className="px-4 py-3 text-right font-mono text-[var(--fg-muted)]">{t.ledger || "—"}</td>
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
