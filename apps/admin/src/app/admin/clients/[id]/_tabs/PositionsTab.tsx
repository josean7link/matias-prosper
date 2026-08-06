"use client";
import { Badge } from "@prosper/ui";
import { useClientPositions } from "@/lib/admin-clients";
import { fmtMoney, fmtDate } from "@/lib/utils";

export default function PositionsTab({ orgId }: { orgId: string }) {
  const swr = useClientPositions(orgId);
  return (
    <div data-testid="tab-content-positions">
      <table className="w-full text-xs">
        <thead className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
          <tr className="border-b border-border">
            <th className="text-left py-2">Producto</th>
            <th className="text-right py-2">Principal</th>
            <th className="text-right py-2">Accrued</th>
            <th className="text-right py-2">APR</th>
            <th className="text-left py-2">Start</th>
            <th className="text-left py-2">Maturity</th>
            <th className="text-left py-2">Status</th>
          </tr>
        </thead>
        <tbody>
          {(swr.data?.items ?? []).map((p: any) => (
            <tr key={p.position_id || p.tx_id} className="border-b border-border">
              <td className="py-2 font-mono">{p.product || "—"}</td>
              <td className="py-2 text-right font-mono tabular">{fmtMoney(p.principal || 0)}</td>
              <td className="py-2 text-right font-mono tabular text-success">{fmtMoney(p.accrued || 0)}</td>
              <td className="py-2 text-right font-mono tabular">{(p.apr_bps / 100 || 0).toFixed(2)}%</td>
              <td className="py-2 font-mono text-[10px]">{p.start_date ? fmtDate(p.start_date) : "—"}</td>
              <td className="py-2 font-mono text-[10px]">{p.maturity_date ? fmtDate(p.maturity_date) : "—"}</td>
              <td className="py-2"><Badge tone={p.status === "active" ? "success" : "auto"} size="sm">{p.status}</Badge></td>
            </tr>
          ))}
          {(swr.data?.items ?? []).length === 0 && (
            <tr><td colSpan={7} className="py-8 text-center text-fg-subtle italic">Sin posiciones activas.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
