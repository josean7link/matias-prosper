import { useEffect, useState } from "react";
import api from "@/lib/api";
import { PageHeader, StatusBadge, EnvPill, EmptyState } from "@/components/common";
import { fmtDate } from "@/lib/format";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

export default function Webhooks() {
  const [hooks, setHooks] = useState([]);
  const [active, setActive] = useState(null);
  const [deliveries, setDeliveries] = useState([]);
  useEffect(() => { api.get("/integrations/webhooks").then(({ data }) => setHooks(data.items || [])); }, []);

  const view = async (h) => {
    setActive(h);
    const { data } = await api.get(`/integrations/webhooks/${h.endpoint_id}/deliveries`);
    setDeliveries(data.items || []);
  };

  return (
    <div data-testid="webhooks-page">
      <PageHeader title="Webhooks" subtitle={`${hooks.length} endpoints configured`} />
      {hooks.length === 0 ? <EmptyState title="No webhook endpoints" /> : (
        <div className="prosper-card overflow-hidden">
          <table className="data-table w-full">
            <thead><tr>
              <th className="text-left px-4 py-3">URL</th>
              <th className="text-left px-4 py-3">Env</th>
              <th className="text-left px-4 py-3">Events</th>
              <th className="text-left px-4 py-3">Created</th>
              <th className="text-left px-4 py-3">Status</th>
            </tr></thead>
            <tbody>
              {hooks.map((h) => (
                <tr key={h.endpoint_id} className="cursor-pointer" onClick={() => view(h)}
                    data-testid={`webhook-row-${h.endpoint_id}`}>
                  <td className="px-4 py-3 font-mono text-xs text-[var(--fg)]">{h.url}</td>
                  <td className="px-4 py-3"><EnvPill env={h.environment} /></td>
                  <td className="px-4 py-3 text-xs">{h.events?.join(", ")}</td>
                  <td className="px-4 py-3 text-xs font-mono text-[var(--fg-muted)]">{fmtDate(h.created_at)}</td>
                  <td className="px-4 py-3"><StatusBadge value={h.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Dialog open={!!active} onOpenChange={(o) => !o && setActive(null)}>
        <DialogContent className="max-w-3xl bg-[var(--surface)] border-[var(--border-strong)]">
          <DialogHeader><DialogTitle className="font-mono text-sm">{active?.url}</DialogTitle></DialogHeader>
          <div className="max-h-[60vh] overflow-y-auto">
            <table className="data-table w-full">
              <thead><tr><th className="text-left py-2">When</th><th className="text-left">Event</th><th className="text-right">Code</th><th className="text-left">Delivered</th></tr></thead>
              <tbody>
                {deliveries.map((d) => (
                  <tr key={d.delivery_id}>
                    <td className="py-2 font-mono text-xs text-[var(--fg-muted)]">{fmtDate(d.created_at, true)}</td>
                    <td className="py-2 text-xs">{d.event_type}</td>
                    <td className="py-2 text-right font-mono">
                      <span className={d.response_status === 200 ? "text-[var(--success)]" : "text-[var(--danger)]"}>{d.response_status}</span>
                    </td>
                    <td className="py-2 text-xs">{d.delivered ? "yes" : "no"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
