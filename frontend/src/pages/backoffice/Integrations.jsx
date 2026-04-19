import { useEffect, useState } from "react";
import api from "@/lib/api";
import { PageHeader, StatusBadge, EnvPill, EmptyState } from "@/components/common";
import { fmtDate } from "@/lib/format";

export default function Integrations() {
  const [apps, setApps] = useState([]);
  useEffect(() => { api.get("/integrations/apps").then(({ data }) => setApps(data.items || [])); }, []);

  return (
    <div data-testid="integrations-page">
      <PageHeader title="Integrations" subtitle={`${apps.length} API apps across partners`} />
      {apps.length === 0 ? <EmptyState title="No apps" /> : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {apps.map((a) => (
            <div key={a.app_id} className="prosper-card p-5" data-testid={`app-${a.app_id}`}>
              <div className="flex justify-between items-start mb-3">
                <div className="font-display font-bold text-lg">{a.name}</div>
                <EnvPill env={a.environment} />
              </div>
              <div className="text-sm text-[var(--fg-muted)] mb-3">{a.description}</div>
              <div className="flex justify-between items-center pt-3 border-t border-[var(--border)]">
                <span className="font-mono text-xs text-[var(--fg-subtle)]">{fmtDate(a.created_at)}</span>
                <StatusBadge value={a.status} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
