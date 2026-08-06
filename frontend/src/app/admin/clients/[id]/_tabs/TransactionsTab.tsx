"use client";
import Link from "next/link";
import { Badge } from "@prosper/ui";
import { useClientTransactions } from "@/lib/admin-clients";
import { fmtMoney, fmtDate } from "@/lib/utils";

export default function TransactionsTab({ orgId }: { orgId: string }) {
  const swr = useClientTransactions(orgId);
  return (
    <div data-testid="tab-content-transactions">
      <table className="w-full text-xs">
        <thead className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
          <tr className="border-b border-border">
            <th className="text-left py-2">When</th>
            <th className="text-left py-2">TX ID</th>
            <th className="text-left py-2">Type</th>
            <th className="text-right py-2">Amount</th>
            <th className="text-left py-2">Status</th>
          </tr>
        </thead>
        <tbody>
          {(swr.data?.items ?? []).map((t: any) => (
            <tr key={t.tx_id} className="border-b border-border">
              <td className="py-2 font-mono text-[10px]">{fmtDate(t.created_at)}</td>
              <td className="py-2">
                <Link href={`/admin/operations/transactions/${t.tx_id}`}
                      className="font-mono text-[11px] text-primary hover:underline">
                  {t.prosper_tx_id || t.tx_id?.slice(0, 12)}
                </Link>
              </td>
              <td className="py-2"><Badge tone="auto" size="sm">{t.type}</Badge></td>
              <td className="py-2 text-right font-mono tabular">{fmtMoney(t.amount || 0)}</td>
              <td className="py-2">
                <Badge tone={t.status === "confirmed" ? "success" : t.status === "failed" ? "danger" : "warning"} size="sm">
                  {t.status}</Badge>
              </td>
            </tr>
          ))}
          {(swr.data?.items ?? []).length === 0 && (
            <tr><td colSpan={5} className="py-8 text-center text-fg-subtle italic">Sin transacciones.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
