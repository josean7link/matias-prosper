import { useEffect, useState } from "react";
import api from "@/lib/api";
import { PageHeader, EnvPill, EmptyState } from "@/components/common";
import Pagination from "@/components/Pagination";
import DateRangeFilter from "@/components/DateRangeFilter";
import ExportButton from "@/components/ExportButton";
import { fmtDateTime } from "@/lib/format";
import { Input } from "@/components/ui/input";

export default function AuditLog() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const pageSize = 50;
  const [actor, setActor] = useState("");
  const [action, setAction] = useState("");
  const [dateRange, setDateRange] = useState({ from: "", to: "" });

  useEffect(() => {
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    if (actor) params.set("actor_email", actor);
    if (action) params.set("action", action);
    if (dateRange.from) params.set("from", dateRange.from);
    if (dateRange.to) params.set("to", dateRange.to);
    api.get(`/audit-logs?${params}`).then(({ data }) => {
      setItems(data.items || []);
      setTotal(data.total || 0);
    });
  }, [actor, action, page, dateRange]);

  useEffect(() => { setPage(1); }, [actor, action, dateRange]);

  return (
    <div data-testid="audit-log-page">
      <PageHeader title="Audit Log" subtitle={`${total.toLocaleString()} events`}
        actions={
          <ExportButton filename={`audit_${new Date().toISOString().slice(0,10)}`}
                        rows={items.map(a => ({
                          created_at: a.created_at, actor_email: a.actor_email,
                          action: a.action, resource: a.resource, resource_id: a.resource_id,
                          environment: a.environment, ip: a.ip,
                        }))}
                        testId="audit-export" />
        }
      />
      <div className="flex gap-3 mb-4 flex-wrap">
        <Input placeholder="Filter by email…"
               className="max-w-xs bg-[var(--surface)] border-[var(--border)] rounded-full font-mono text-xs h-9"
               value={actor} onChange={(e) => setActor(e.target.value)} data-testid="audit-actor" />
        <Input placeholder="Filter by action…"
               className="max-w-xs bg-[var(--surface)] border-[var(--border)] rounded-full font-mono text-xs h-9"
               value={action} onChange={(e) => setAction(e.target.value)} data-testid="audit-action" />
        <DateRangeFilter from={dateRange.from} to={dateRange.to} onChange={setDateRange} testId="audit-date-range" />
      </div>
      {items.length === 0 ? <EmptyState title="No audit events" /> : (
        <div className="prosper-card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="data-table w-full">
              <thead><tr>
                <th>When</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Resource</th>
                <th>Resource ID</th>
                <th>Env</th>
                <th>IP</th>
              </tr></thead>
              <tbody>
                {items.map((a) => (
                  <tr key={a.audit_id} data-testid={`audit-${a.audit_id}`}>
                    <td className="font-mono text-xs text-[var(--fg-muted)]">{fmtDateTime(a.created_at)}</td>
                    <td className="text-xs font-mono text-[var(--fg)]">{a.actor_email || "system"}</td>
                    <td className="text-sm text-[var(--fg)]">{a.action}</td>
                    <td className="text-xs uppercase tracking-wider text-[var(--fg-muted)]">{a.resource}</td>
                    <td className="text-xs font-mono text-[var(--fg-subtle)]">{a.resource_id ? a.resource_id.slice(0, 16) + "…" : "—"}</td>
                    <td><EnvPill env={a.environment} /></td>
                    <td className="text-xs font-mono text-[var(--fg-subtle)]">{a.ip || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination page={page} pageSize={pageSize} total={total} onPageChange={setPage} testId="audit-pagination" />
        </div>
      )}
    </div>
  );
}
