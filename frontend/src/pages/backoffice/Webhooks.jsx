import { useEffect, useState } from "react";
import api from "@/lib/api";
import { PageHeader, StatusBadge, EnvPill, EmptyState } from "@/components/common";
import FormDialog from "@/components/FormDialog";
import { fmtDate } from "@/lib/format";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { Plus } from "@phosphor-icons/react";

const EVENT_CHOICES = [
  "transaction.confirmed", "transaction.failed",
  "position.matured", "position.redeemed",
  "onboarding.approved", "onboarding.rejected",
  "alert.critical",
];

export default function Webhooks() {
  const [hooks, setHooks] = useState([]);
  const [apps, setApps] = useState([]);
  const [orgs, setOrgs] = useState([]);
  const [active, setActive] = useState(null);
  const [deliveries, setDeliveries] = useState([]);
  const [createOpen, setCreateOpen] = useState(false);

  const load = () => api.get("/integrations/webhooks").then(({ data }) => setHooks(data.items || []));
  useEffect(() => {
    load();
    api.get("/integrations/apps").then(({ data }) => setApps(data.items || []));
    api.get("/organizations").then(({ data }) => setOrgs(data.items || []));
  }, []);

  const view = async (h) => {
    setActive(h);
    const { data } = await api.get(`/integrations/webhooks/${h.endpoint_id}/deliveries`);
    setDeliveries(data.items || []);
  };

  const createHook = async (values) => {
    const payload = {
      ...values,
      events: (values.events || "transaction.confirmed").split(",").map(e => e.trim()).filter(Boolean),
    };
    await api.post("/integrations/webhooks", payload);
    toast.success("Webhook endpoint created");
    load();
  };

  return (
    <div data-testid="webhooks-page">
      <PageHeader title="Webhooks" subtitle={`${hooks.length} endpoints configured`}
        actions={
          <Button onClick={() => setCreateOpen(true)} data-testid="create-webhook-btn"
                  className="rounded-full bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white gap-1.5">
            <Plus size={14} weight="bold" /> New Webhook
          </Button>
        }
      />
      {hooks.length === 0 ? <EmptyState title="No webhook endpoints" /> : (
        <div className="prosper-card overflow-hidden">
          <table className="data-table w-full">
            <thead><tr>
              <th>URL</th><th>Env</th><th>Events</th><th>Created</th><th>Status</th>
            </tr></thead>
            <tbody>
              {hooks.map((h) => (
                <tr key={h.endpoint_id} className="cursor-pointer" onClick={() => view(h)}
                    data-testid={`webhook-row-${h.endpoint_id}`}>
                  <td className="font-mono text-xs text-[var(--fg)]">{h.url}</td>
                  <td><EnvPill env={h.environment} /></td>
                  <td className="text-xs">{h.events?.join(", ")}</td>
                  <td className="text-xs font-mono text-[var(--fg-muted)]">{fmtDate(h.created_at)}</td>
                  <td><StatusBadge value={h.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <FormDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        title="New Webhook Endpoint"
        description="Receive real-time events from Prosper. We'll sign payloads with HMAC-SHA256."
        submitLabel="Create Endpoint"
        onSubmit={createHook}
        testId="create-webhook-dialog"
        fields={[
          { key: "url", label: "URL", required: true, placeholder: "https://api.yourcompany.com/hooks/prosper",
            help: "Must be HTTPS. We'll POST JSON payloads here." },
          { key: "org_id", label: "Organization", type: "select", required: true,
            options: orgs.map(o => ({ value: o.org_id, label: o.name })) },
          { key: "app_id", label: "API App", type: "select", required: true,
            options: apps.map(a => ({ value: a.app_id, label: `${a.name} (${a.environment})` })) },
          { key: "environment", label: "Environment", type: "select", default: "sandbox",
            options: [{ value: "sandbox", label: "Sandbox" }, { value: "production", label: "Production" }] },
          { key: "events", label: "Events", default: "transaction.confirmed,position.matured",
            help: "Comma-separated. Available: " + EVENT_CHOICES.join(", ") },
        ]}
      />

      <Dialog open={!!active} onOpenChange={(o) => !o && setActive(null)}>
        <DialogContent className="max-w-3xl bg-[var(--surface)] border-[var(--border)] rounded-xl">
          <DialogHeader><DialogTitle className="font-mono text-sm">{active?.url}</DialogTitle></DialogHeader>
          <div className="max-h-[60vh] overflow-y-auto">
            <table className="data-table w-full">
              <thead><tr><th>When</th><th>Event</th><th className="text-right">Code</th><th>Delivered</th></tr></thead>
              <tbody>
                {deliveries.map((d) => (
                  <tr key={d.delivery_id}>
                    <td className="font-mono text-xs text-[var(--fg-muted)]">{fmtDate(d.created_at, true)}</td>
                    <td className="text-xs">{d.event_type}</td>
                    <td className="text-right font-mono">
                      <span style={{ color: d.response_status === 200 ? "var(--success)" : "var(--danger)" }}>
                        {d.response_status}
                      </span>
                    </td>
                    <td className="text-xs">{d.delivered ? "yes" : "no"}</td>
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
