import { useEffect, useState } from "react";
import api from "@/lib/api";
import { PageHeader, StatusBadge, StellarLink, CopyField, EmptyState, MetricBar, MetricCell } from "@/components/common";
import { fmtMoney, fmtDateTime } from "@/lib/format";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";

export default function Reconciliation() {
  const [items, setItems] = useState([]);
  const [filter, setFilter] = useState("all");

  const load = async () => {
    const params = new URLSearchParams();
    if (filter !== "all") params.set("status", filter);
    const { data } = await api.get(`/reconciliation?${params}`);
    setItems(data.items || []);
  };
  useEffect(() => { load(); }, [filter]);

  const resolve = async (id) => {
    await api.post(`/reconciliation/${id}/resolve`);
    toast.success("Reconciliation resolved");
    load();
  };

  const matched = items.filter(i => i.status === "matched").length;
  const inv = items.filter(i => i.status === "investigating").length;
  const unm = items.filter(i => i.status === "unmatched").length;

  return (
    <div data-testid="reconciliation-page">
      <PageHeader title="Reconciliation" subtitle="Offchain ledger ↔ on-chain memo matching" />
      <MetricBar>
        <MetricCell label="Total" value={items.length} />
        <MetricCell label="Matched" value={matched} />
        <MetricCell label="Investigating" value={inv} />
        <MetricCell label="Unmatched" value={unm} />
      </MetricBar>
      <div className="mt-4 mb-4">
        <Select value={filter} onValueChange={setFilter}>
          <SelectTrigger className="w-[200px] bg-[var(--surface)] border-[var(--border)] rounded-md" data-testid="recon-filter">
            <SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All records</SelectItem>
            <SelectItem value="matched">Matched</SelectItem>
            <SelectItem value="investigating">Investigating</SelectItem>
            <SelectItem value="unmatched">Unmatched</SelectItem>
            <SelectItem value="resolved">Resolved</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {items.length === 0 ? <EmptyState title="No records" /> : (
        <div className="prosper-card overflow-x-auto">
          <table className="data-table w-full">
            <thead><tr>
              <th className="text-left px-4 py-3">prosperTxId</th>
              <th className="text-left px-4 py-3">Tx Hash</th>
              <th className="text-right px-4 py-3">Amount</th>
              <th className="text-left px-4 py-3">Type</th>
              <th className="text-left px-4 py-3">Discrepancy</th>
              <th className="text-left px-4 py-3">Status</th>
              <th className="text-right px-4 py-3">Actions</th>
            </tr></thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.recon_id} data-testid={`recon-row-${r.recon_id}`}>
                  <td className="px-4 py-3"><CopyField value={r.prosper_tx_id} /></td>
                  <td className="px-4 py-3"><StellarLink hash={r.tx_hash} /></td>
                  <td className="px-4 py-3 text-right font-mono">{r.tx ? fmtMoney(r.tx.amount) : "—"}</td>
                  <td className="px-4 py-3 capitalize text-xs">{r.tx?.type || "—"}</td>
                  <td className="px-4 py-3 text-xs text-[var(--warning)]">{r.discrepancy || "—"}</td>
                  <td className="px-4 py-3"><StatusBadge value={r.status} /></td>
                  <td className="px-4 py-3 text-right">
                    {r.status !== "matched" && r.status !== "resolved" && (
                      <Button size="sm" onClick={() => resolve(r.recon_id)}
                              className="h-7 text-xs bg-[#0066FF] hover:bg-[#0052CC] rounded-sm"
                              data-testid={`resolve-${r.recon_id}`}>Resolve</Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
