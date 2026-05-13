"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { PageHeader, Badge, DataTable, StatusDot, type Column } from "@prosper/ui";
import { Search, ChevronLeft, ChevronRight, Download, X, Copy, ExternalLink, AlertTriangle } from "lucide-react";
import { toast } from "sonner";
import { useTransactions, csvExportUrl, type TxFilters, type TxRow } from "@/lib/operations";
import { fmtMoney, cn } from "@/lib/utils";

const TYPES = ["subscribe", "redeem", "mint", "transfer", "onramp", "offramp"] as const;
const STATUSES = ["confirmed", "pending", "failed"] as const;

const typeTone: Record<string, "success" | "warning" | "primary" | "default"> = {
  subscribe: "success", onramp: "success",
  redeem: "warning",    offramp: "warning",
  mint: "primary",      transfer: "default",
};

const statusTone: Record<string, "green" | "yellow" | "red" | "gray"> = {
  confirmed: "green", pending: "yellow", failed: "red",
};

function shortHash(s: string | null | undefined, l = 6, r = 4): string {
  if (!s) return "—";
  if (s.length <= l + r + 3) return s;
  return `${s.slice(0, l)}…${s.slice(-r)}`;
}

export default function LedgerPage() {
  const router = useRouter();
  const [filters, setFilters] = useState<TxFilters>({ page: 1, limit: 50 });
  const swr = useTransactions(filters);

  const updateFilter = (next: Partial<TxFilters>) =>
    setFilters((f) => ({ ...f, ...next, page: 1 }));

  const toggleArrayFilter = (key: "type" | "status", value: string) => {
    setFilters((f) => {
      const list = new Set(f[key] || []);
      if (list.has(value)) list.delete(value); else list.add(value);
      return { ...f, [key]: list.size ? Array.from(list) : undefined, page: 1 };
    });
  };

  const clearFilters = () => setFilters({ page: 1, limit: 50 });
  const hasFilters = useMemo(
    () => !!(filters.type?.length || filters.status?.length ||
            filters.org_id || filters.search ||
            filters.date_from || filters.date_to || filters.only_errors),
    [filters],
  );

  const cols: Column<TxRow>[] = [
    {
      key: "created_at", header: "When", width: "150px", sortable: true,
      render: (r) => (
        <span className="font-mono text-[11px] text-fg-muted whitespace-nowrap"
              title={r.created_at}>
          {new Date(r.created_at).toLocaleString("en-US",
            { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" })}
        </span>
      ),
    },
    {
      key: "prosper_tx_id", header: "Prosper Tx", width: "140px",
      render: (r) => (
        <button onClick={(e) => { e.stopPropagation();
          navigator.clipboard.writeText(r.prosper_tx_id);
          toast.success("Copied"); }}
          className="font-mono text-[11px] text-fg hover:text-primary
                     inline-flex items-center gap-1"
          title={r.prosper_tx_id}
          data-testid={`copy-ptx-${r.tx_id}`}>
          {shortHash(r.prosper_tx_id)} <Copy size={10} />
        </button>
      ),
    },
    {
      key: "type", header: "Type", width: "110px",
      render: (r) => <Badge tone={typeTone[r.type] || "default"} size="sm">{r.type}</Badge>,
    },
    {
      key: "org_name", header: "Client", width: "160px",
      render: (r) => (
        <Link href={`/admin/operations/by-client/${r.org_id}`}
              onClick={(e) => e.stopPropagation()}
              className="text-fg hover:text-primary truncate block">
          {r.org_name}
        </Link>
      ),
    },
    {
      key: "amount", header: "Amount", width: "140px", align: "right", numeric: true,
      render: (r) => (
        <span className="font-mono tabular text-fg">
          {fmtMoney(r.amount)} <span className="text-fg-subtle text-[10px]">{r.asset}</span>
        </span>
      ),
    },
    {
      key: "status", header: "Status", width: "100px",
      render: (r) => (
        <span className="inline-flex items-center gap-1.5 text-[11px] font-mono uppercase">
          <StatusDot color={statusTone[r.status] || "gray"} />{r.status}
        </span>
      ),
    },
    {
      key: "tx_hash", header: "Stellar", width: "120px",
      render: (r) => r.tx_hash ? (
        <a href={`https://stellar.expert/explorer/public/tx/${r.tx_hash}`}
           target="_blank" rel="noreferrer"
           onClick={(e) => e.stopPropagation()}
           className="font-mono text-[10px] text-primary hover:underline
                      inline-flex items-center gap-1"
           data-testid={`stellar-link-${r.tx_id}`}>
          {shortHash(r.tx_hash, 5, 4)} <ExternalLink size={10} />
        </a>
      ) : <span className="text-fg-subtle text-[10px]">—</span>,
    },
  ];

  return (
    <div data-testid="ledger-page">
      <PageHeader
        breadcrumbs={[{ label: "Admin", href: "/admin" },
                      { label: "Operations", href: "/admin/operations" },
                      { label: "Ledger" }]}
        kicker="Phase 3 · Operations"
        title="Transactions ledger"
        subtitle="Global cross-org ledger. Click any row to open the full lifecycle view."
        actions={
          <a href={csvExportUrl(filters)} target="_blank" rel="noreferrer"
             className="prosper-btn-ghost h-9 text-xs gap-1.5"
             data-testid="ledger-export-csv">
            <Download size={13} /> Export CSV
          </a>
        }
      />

      {/* Filters bar */}
      <div className="prosper-card p-3 mb-4 space-y-3" data-testid="ledger-filters">
        {/* Search + only-errors */}
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative flex-1 min-w-[220px]">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-subtle" />
            <input
              placeholder="Search tx_hash, prosperTxId, memo…"
              defaultValue={filters.search || ""}
              onKeyDown={(e) => {
                if (e.key === "Enter") updateFilter({ search: (e.target as HTMLInputElement).value || undefined });
              }}
              data-testid="ledger-search"
              className="prosper-input pl-7 h-8 w-full text-xs" />
          </div>
          <label className="inline-flex items-center gap-1.5 text-[11px] font-mono
                            uppercase tracking-wider text-fg-muted cursor-pointer
                            select-none">
            <input type="checkbox" checked={!!filters.only_errors}
              onChange={(e) => updateFilter({ only_errors: e.target.checked })}
              data-testid="ledger-only-errors" />
            <AlertTriangle size={11} /> Only errors
          </label>
          <input type="date" value={filters.date_from || ""}
            onChange={(e) => updateFilter({ date_from: e.target.value || undefined })}
            data-testid="ledger-date-from"
            className="prosper-input h-8 text-xs w-[140px]" />
          <span className="text-fg-subtle text-xs">→</span>
          <input type="date" value={filters.date_to || ""}
            onChange={(e) => updateFilter({ date_to: e.target.value || undefined })}
            data-testid="ledger-date-to"
            className="prosper-input h-8 text-xs w-[140px]" />
          {hasFilters && (
            <button onClick={clearFilters}
              data-testid="ledger-clear-filters"
              className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle
                         hover:text-danger inline-flex items-center gap-0.5">
              <X size={12} /> Clear
            </button>
          )}
        </div>
        {/* Type chips */}
        <div className="flex flex-wrap gap-1.5">
          <span className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle
                            self-center mr-1">Type</span>
          {TYPES.map((t) => {
            const active = filters.type?.includes(t);
            return (
              <Chip key={t} active={!!active}
                onClick={() => toggleArrayFilter("type", t)}
                testid={`chip-type-${t}`}>{t}</Chip>
            );
          })}
          <span className="w-2" />
          <span className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle
                            self-center mr-1">Status</span>
          {STATUSES.map((s) => {
            const active = filters.status?.includes(s);
            return (
              <Chip key={s} active={!!active}
                onClick={() => toggleArrayFilter("status", s)}
                testid={`chip-status-${s}`}>{s}</Chip>
            );
          })}
        </div>
      </div>

      {/* Table */}
      <DataTable<TxRow>
        data={swr.data?.items ?? []} columns={cols}
        rowKey={(r) => r.tx_id}
        empty={swr.isLoading ? "Loading…" : "No transactions match"}
        onRowClick={(r) => router.push(`/admin/operations/transactions/${r.tx_id}`)}
      />

      {/* Pagination */}
      {swr.data && swr.data.pages > 1 && (
        <div className="flex items-center justify-between mt-3 text-xs"
             data-testid="ledger-pagination">
          <span className="text-fg-subtle font-mono">
            Page {swr.data.page} of {swr.data.pages} · {swr.data.total} txs
          </span>
          <div className="flex gap-1">
            <button onClick={() => setFilters((f) => ({ ...f, page: Math.max(1, (f.page || 1) - 1) }))}
              disabled={swr.data.page <= 1}
              data-testid="ledger-prev"
              className="prosper-btn-ghost h-8 w-8 p-0 disabled:opacity-30">
              <ChevronLeft size={14} />
            </button>
            <button onClick={() => setFilters((f) => ({ ...f, page: Math.min(swr.data!.pages, (f.page || 1) + 1) }))}
              disabled={swr.data.page >= swr.data.pages}
              data-testid="ledger-next"
              className="prosper-btn-ghost h-8 w-8 p-0 disabled:opacity-30">
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function Chip({ active, onClick, children, testid }:
  { active: boolean; onClick: () => void; children: React.ReactNode; testid: string }) {
  return (
    <button onClick={onClick} data-testid={testid}
      className={cn(
        "h-7 px-2.5 rounded-full text-[10px] font-mono uppercase tracking-wider transition-colors",
        active
          ? "bg-fg text-bg"
          : "bg-surface text-fg-muted hover:text-fg border border-border",
      )}>
      {children}
    </button>
  );
}
