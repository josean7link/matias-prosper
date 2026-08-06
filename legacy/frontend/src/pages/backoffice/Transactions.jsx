import { useEffect, useState } from "react";
import api from "@/lib/api";
import { useApp } from "@/contexts/AppContext";
import { PageHeader, StatusBadge, StellarLink, CopyField, EmptyState } from "@/components/common";
import FormDialog from "@/components/FormDialog";
import Pagination from "@/components/Pagination";
import DateRangeFilter from "@/components/DateRangeFilter";
import ExportButton from "@/components/ExportButton";
import { fmtMoney, fmtDateTime } from "@/lib/format";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { Coins } from "@phosphor-icons/react";

export default function Transactions() {
  const { env } = useApp();
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const pageSize = 50;
  const [funds, setFunds] = useState([]);
  const [search, setSearch] = useState("");
  const [type, setType] = useState("all");
  const [status, setStatus] = useState("all");
  const [dateRange, setDateRange] = useState({ from: "", to: "" });
  const [mintOpen, setMintOpen] = useState(false);

  const load = () => {
    const params = new URLSearchParams({ env, page: String(page), page_size: String(pageSize) });
    if (search) params.set("search", search);
    if (type !== "all") params.set("type", type);
    if (status !== "all") params.set("status", status);
    if (dateRange.from) params.set("from", dateRange.from);
    if (dateRange.to) params.set("to", dateRange.to);
    api.get(`/transactions?${params}`).then(({ data }) => {
      setItems(data.items || []);
      setTotal(data.total || 0);
    });
  };

  useEffect(() => {
    load();
    api.get(`/funds?env=${env}`).then(({ data }) => setFunds(data.items || []));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, type, status, env, page, dateRange]);

  // Reset to page 1 when filters change
  useEffect(() => { setPage(1); }, [search, type, status, env, dateRange]);

  const mint = async (values) => {
    const { data } = await api.post("/transactions/mint", {
      fund_id: values.fund_id,
      amount: Number(values.amount),
      reason: values.reason,
    });
    if (data.status === "pending_approval") {
      toast.success(`Approval requested · ${data.approval.approval_id.slice(0, 12)}…`);
    } else {
      toast.success(`Mint submitted`);
    }
    load();
  };

  const exportRows = items.map((t) => ({
    created_at: t.created_at,
    type: t.type,
    amount: t.amount,
    asset: t.asset_code,
    status: t.status,
    prosper_tx_id: t.prosper_tx_id,
    tx_hash: t.tx_hash,
    ledger: t.ledger,
    from: t.from_address,
    to: t.to_address,
    memo: t.memo,
    environment: t.environment,
  }));

  return (
    <div data-testid="transactions-page">
      <PageHeader title="Transactions Ledger" subtitle={`${total.toLocaleString()} transactions · ${env}`}
        actions={
          <div className="flex gap-2">
            <ExportButton filename={`transactions_${env}_${new Date().toISOString().slice(0,10)}`}
                          rows={exportRows} testId="tx-export" />
            <Button onClick={() => setMintOpen(true)} data-testid="mint-btn"
                    className="rounded-full bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white gap-1.5">
              <Coins size={14} weight="bold" /> Mint PROS
            </Button>
          </div>
        }
      />
      <div className="flex gap-3 mb-4 flex-wrap">
        <Input placeholder="Search hash, prosperTxId, memo…"
               className="max-w-sm bg-[var(--surface)] border-[var(--border)] rounded-full font-mono text-xs h-9"
               value={search} onChange={(e) => setSearch(e.target.value)} data-testid="tx-search" />
        <Select value={type} onValueChange={setType}>
          <SelectTrigger className="w-[160px] bg-[var(--surface)] border-[var(--border)] rounded-full h-9" data-testid="tx-filter-type">
            <SelectValue placeholder="Type" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All types</SelectItem>
            {["mint", "burn", "subscribe", "redeem", "transfer", "deposit", "withdraw", "claim", "fund", "fee"].map(t =>
              <SelectItem key={t} value={t}>{t}</SelectItem>
            )}
          </SelectContent>
        </Select>
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger className="w-[160px] bg-[var(--surface)] border-[var(--border)] rounded-full h-9" data-testid="tx-filter-status">
            <SelectValue placeholder="Status" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All</SelectItem>
            {["pending", "submitted", "confirmed", "failed", "retrying"].map(s =>
              <SelectItem key={s} value={s}>{s}</SelectItem>
            )}
          </SelectContent>
        </Select>
        <DateRangeFilter from={dateRange.from} to={dateRange.to} onChange={setDateRange} testId="tx-date-range" />
      </div>
      {items.length === 0 ? <EmptyState title="No transactions match" /> : (
        <div className="prosper-card overflow-hidden">
          <div className="overflow-x-auto">
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
          <Pagination page={page} pageSize={pageSize} total={total} onPageChange={setPage} testId="tx-pagination" />
        </div>
      )}

      <FormDialog
        open={mintOpen}
        onOpenChange={setMintOpen}
        title="Mint PROS Tokens"
        description="Issues new PROS tokens from the issuer account to the treasury. Requires finance/ops/admin role."
        submitLabel="Submit Mint"
        onSubmit={mint}
        testId="mint-dialog"
        fields={[
          { key: "fund_id", label: "Fund", type: "select", required: true,
            options: funds.map(f => ({ value: f.fund_id, label: `${f.code} · ${f.name} (${f.environment})` })) },
          { key: "amount", label: "Amount (PROS)", type: "number", required: true, placeholder: "100000" },
          { key: "reason", label: "Reason / Reference", required: true, type: "textarea",
            placeholder: "Q1 2026 fund inflow — Quirón PyMEs subscription batch",
            help: "This appears in the audit log. Be specific; compliance requires traceability." },
        ]}
      />
    </div>
  );
}
