"use client";
import Link from "next/link";
import { useState, useMemo } from "react";
import { Download, FilterIcon } from "lucide-react";
import { PageHeader, Badge } from "@prosper/ui";
import { RefreshButton } from "@/components/PageActions";
import { useTxHistory, fmtCur } from "@/lib/alfred";

const TYPE_LABEL: Record<string, string> = {
  onramp:    "Carga (onramp)",
  offramp:   "Retiro (offramp)",
  subscribe: "Suscripción",
  redeem:    "Rescate",
  yield_accrual: "Yield",
  payout:    "Payout",
  fee:       "Fee",
};

const TYPE_TONE: Record<string, "success" | "warning" | "info" | "default"> = {
  onramp: "success",
  offramp: "default",
  subscribe: "info",
  redeem: "warning",
};

const ALL_TYPES = ["onramp", "offramp", "subscribe", "redeem", "yield_accrual", "payout"];
const ALL_STATUS = ["pending", "confirmed", "failed", "reversed"];

export default function TransactionsHistoryPage() {
  const [type, setType] = useState("");
  const [status, setStatus] = useState("");
  const { data, isLoading, mutate } = useTxHistory({ type, status });

  const rows = data?.items ?? [];

  const exportCsv = useMemo(() => () => {
    const headers = ["created_at", "type", "amount", "asset", "status", "tx_id", "memo"];
    const csv = [
      headers.join(","),
      ...rows.map((r) => [
        r.created_at, r.type, r.amount, r.asset, r.status, r.tx_id,
        `"${(r.memo || "").replace(/"/g, '""')}"`,
      ].join(",")),
    ].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `prosper-transactions-${new Date().toISOString().slice(0,10)}.csv`;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  }, [rows]);

  return (
    <div data-testid="tx-history">
      <PageHeader
        breadcrumbs={[{ label: "Client", href: "/client" }, { label: "Movimientos" }]}
        kicker="Phase 8 · Historial"
        title="Movimientos"
        subtitle="Todas tus operaciones — onramps, suscripciones, rescates, retiros."
        actions={
          <div className="flex items-center gap-2">
            <button onClick={exportCsv} disabled={rows.length === 0}
              className="prosper-btn-ghost h-9 text-xs gap-1.5 disabled:opacity-40"
              data-testid="tx-export">
              <Download size={13} /> CSV
            </button>
            <RefreshButton onClick={() => mutate()} />
          </div>
        }
      />

      {/* Filters */}
      <div className="prosper-card p-3 mb-4 flex flex-wrap items-center gap-2"
           data-testid="tx-filters">
        <FilterIcon size={12} className="text-fg-subtle ml-2" />
        <Select label="Tipo" value={type} setValue={setType} options={ALL_TYPES} testid="filter-type" />
        <Select label="Status" value={status} setValue={setStatus} options={ALL_STATUS} testid="filter-status" />
        {(type || status) && (
          <button onClick={() => { setType(""); setStatus(""); }}
            className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle hover:text-fg ml-2"
            data-testid="filter-clear">
            Limpiar
          </button>
        )}
        <span className="ml-auto text-[11px] font-mono text-fg-subtle">
          {isLoading ? "Cargando…" : `${rows.length} resultados`}
        </span>
      </div>

      {/* Table */}
      <div className="prosper-card overflow-hidden">
        {rows.length === 0 ? (
          <div className="p-10 text-center text-fg-subtle text-sm">
            Sin movimientos {(type || status) ? "con esos filtros" : "aún"}.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="tx-table">
              <thead>
                <tr className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle border-b border-border">
                  <Th>Fecha</Th>
                  <Th>Tipo</Th>
                  <Th right>Monto</Th>
                  <Th>Status</Th>
                  <Th>Memo</Th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.tx_id} className="border-b border-border/50 hover:bg-surface-hover"
                      data-testid={`tx-row-${r.tx_id}`}>
                    <Td>
                      <span className="text-xs font-mono text-fg-muted">
                        {new Date(r.created_at).toLocaleString()}
                      </span>
                    </Td>
                    <Td>
                      <Badge tone={TYPE_TONE[r.type] || "default"} size="sm">
                        {TYPE_LABEL[r.type] || r.type}
                      </Badge>
                    </Td>
                    <Td right>
                      <span className="font-mono tabular-nums">
                        {fmtCur(r.amount, "USDC")} {r.asset}
                      </span>
                    </Td>
                    <Td>
                      <Badge tone={r.status === "confirmed" ? "success"
                                : r.status === "failed" ? "danger"
                                : "warning"} size="sm">
                        {r.status}
                      </Badge>
                    </Td>
                    <Td>
                      <span className="text-xs text-fg-muted line-clamp-1">{r.memo || "—"}</span>
                    </Td>
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

function Select({ label, value, setValue, options, testid }:
  { label: string; value: string; setValue: (v: string) => void;
    options: string[]; testid: string }) {
  return (
    <label className="flex items-center gap-1 text-xs">
      <span className="text-fg-subtle">{label}</span>
      <select value={value} onChange={(e) => setValue(e.target.value)}
        className="prosper-input h-8 text-xs px-2"
        data-testid={testid}>
        <option value="">Todos</option>
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </label>
  );
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <th className={`px-4 py-2 ${right ? "text-right" : "text-left"} font-normal`}>{children}</th>;
}
function Td({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <td className={`px-4 py-2 ${right ? "text-right" : "text-left"}`}>{children}</td>;
}
