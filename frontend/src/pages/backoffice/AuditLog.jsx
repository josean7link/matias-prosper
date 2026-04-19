import { useEffect, useState } from "react";
import api from "@/lib/api";
import { PageHeader, EnvPill, EmptyState } from "@/components/common";
import { fmtDateTime } from "@/lib/format";
import { Input } from "@/components/ui/input";

export default function AuditLog() {
  const [items, setItems] = useState([]);
  const [actor, setActor] = useState("");
  const [action, setAction] = useState("");

  useEffect(() => {
    const params = new URLSearchParams();
    if (actor) params.set("actor_email", actor);
    if (action) params.set("action", action);
    api.get(`/audit-logs?${params}`).then(({ data }) => setItems(data.items || []));
  }, [actor, action]);

  return (
    <div data-testid="audit-log-page">
      <PageHeader title="Audit Log" subtitle={`${items.length} events`} />
      <div className="flex gap-3 mb-4">
        <Input placeholder="Filter by email…" className="max-w-xs bg-[var(--surface)] border-[var(--border)] rounded-md font-mono text-xs"
               value={actor} onChange={(e) => setActor(e.target.value)} data-testid="audit-actor" />
        <Input placeholder="Filter by action…" className="max-w-xs bg-[var(--surface)] border-[var(--border)] rounded-md font-mono text-xs"
               value={action} onChange={(e) => setAction(e.target.value)} data-testid="audit-action" />
      </div>
      {items.length === 0 ? <EmptyState title="No audit events" /> : (
        <div className="prosper-card overflow-hidden">
          <table className="data-table w-full">
            <thead><tr>
              <th className="text-left px-4 py-3">When</th>
              <th className="text-left px-4 py-3">Actor</th>
              <th className="text-left px-4 py-3">Action</th>
              <th className="text-left px-4 py-3">Resource</th>
              <th className="text-left px-4 py-3">Resource ID</th>
              <th className="text-left px-4 py-3">Env</th>
              <th className="text-left px-4 py-3">IP</th>
            </tr></thead>
            <tbody>
              {items.map((a) => (
                <tr key={a.audit_id} data-testid={`audit-${a.audit_id}`}>
                  <td className="px-4 py-3 font-mono text-xs text-[var(--fg-muted)]">{fmtDateTime(a.created_at)}</td>
                  <td className="px-4 py-3 text-xs font-mono text-[var(--fg)]">{a.actor_email || "system"}</td>
                  <td className="px-4 py-3 text-sm text-[var(--fg)]">{a.action}</td>
                  <td className="px-4 py-3 text-xs uppercase tracking-wider text-[var(--fg-muted)]">{a.resource}</td>
                  <td className="px-4 py-3 text-xs font-mono text-[var(--fg-subtle)]">{a.resource_id ? a.resource_id.slice(0, 16) + "…" : "—"}</td>
                  <td className="px-4 py-3"><EnvPill env={a.environment} /></td>
                  <td className="px-4 py-3 text-xs font-mono text-[var(--fg-subtle)]">{a.ip || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
