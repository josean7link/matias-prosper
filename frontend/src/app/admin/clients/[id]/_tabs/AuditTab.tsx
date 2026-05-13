"use client";
import { useClientAuditLog } from "@/lib/admin-clients";
import { fmtDate } from "@/lib/utils";

export default function AuditTab({ orgId }: { orgId: string }) {
  const swr = useClientAuditLog(orgId);
  return (
    <div data-testid="tab-content-audit">
      <ol className="border-l border-border pl-4 space-y-2">
        {(swr.data?.items ?? []).map((a: any, i: number) => (
          <li key={i} className="text-[11px] font-mono relative">
            <span className="absolute -left-[18px] top-1 w-2 h-2 rounded-full bg-primary"/>
            <span className="text-fg-subtle">{fmtDate(a.ts)}</span>
            <span className="ml-2 text-fg">{a.action}</span>
            <span className="ml-2 text-fg-subtle">{a.actor_email || a.actor_user_id || "—"}</span>
            {a.metadata && Object.keys(a.metadata).length > 0 && (
              <details className="ml-2 inline-block">
                <summary className="cursor-pointer text-fg-subtle text-[10px]">meta</summary>
                <pre className="text-[10px] mt-1 p-2 bg-surface-hover rounded overflow-x-auto">
                  {JSON.stringify(a.metadata, null, 2)}
                </pre>
              </details>
            )}
          </li>
        ))}
        {(swr.data?.items ?? []).length === 0 && (
          <li className="text-fg-subtle text-xs italic">Sin actividad registrada.</li>
        )}
      </ol>
    </div>
  );
}
