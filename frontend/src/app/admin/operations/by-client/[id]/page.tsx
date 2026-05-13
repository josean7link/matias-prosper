"use client";
import { useParams } from "next/navigation";
import Link from "next/link";
import { PageHeader, Badge, DataTable, StatusDot, type Column } from "@prosper/ui";
import { ArrowLeft } from "lucide-react";
import { useTransactions, type TxRow } from "@/lib/operations";
import { fmtMoney } from "@/lib/utils";
import { useRouter } from "next/navigation";

export default function ClientDrillDown() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const swr = useTransactions({ org_id: id, page: 1, limit: 50 });
  const cols: Column<TxRow>[] = [
    { key: "created_at", header: "When", width: "150px",
      render: (r) => <span className="font-mono text-[11px]">
        {new Date(r.created_at).toLocaleString("en-US",
          { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" })}
      </span> },
    { key: "prosper_tx_id", header: "Prosper Tx", width: "150px",
      render: (r) => <span className="font-mono text-[11px]">
        {r.prosper_tx_id.slice(0, 10)}…</span> },
    { key: "type", header: "Type", width: "110px",
      render: (r) => <Badge tone="auto" size="sm">{r.type}</Badge> },
    { key: "amount", header: "Amount", numeric: true, width: "140px", align: "right",
      render: (r) => <span className="font-mono tabular">{fmtMoney(r.amount)}</span> },
    { key: "status", header: "Status", width: "120px",
      render: (r) => <span className="inline-flex items-center gap-1.5 text-[11px] font-mono uppercase">
        <StatusDot color={r.status === "confirmed" ? "green" :
          r.status === "failed" ? "red" : "yellow"} />{r.status}
      </span> },
  ];
  return (
    <div data-testid="by-client-drill">
      <PageHeader
        breadcrumbs={[
          { label: "Admin", href: "/admin" },
          { label: "Operations", href: "/admin/operations" },
          { label: "By client", href: "/admin/operations/by-client" },
          { label: id },
        ]}
        kicker="Phase 3 · Client drill-down"
        title={swr.data?.items?.[0]?.org_name || id}
        subtitle="Histórico de operaciones del cliente."
        actions={
          <Link href="/admin/operations/by-client"
                className="prosper-btn-ghost h-9 text-xs gap-1.5">
            <ArrowLeft size={13} /> Back
          </Link>
        }
      />
      <DataTable<TxRow>
        data={swr.data?.items ?? []} columns={cols}
        rowKey={(r) => r.tx_id}
        empty={swr.isLoading ? "Loading…" : "No operations"}
        onRowClick={(r) => router.push(`/admin/operations/transactions/${r.tx_id}`)} />
    </div>
  );
}
