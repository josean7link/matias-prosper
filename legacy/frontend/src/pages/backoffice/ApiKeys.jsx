import { useEffect, useState } from "react";
import api from "@/lib/api";
import { PageHeader, StatusBadge, EnvPill, CopyField, EmptyState } from "@/components/common";
import FormDialog from "@/components/FormDialog";
import { relativeTime } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { toast } from "sonner";
import { Plus, WarningCircle, Copy } from "@phosphor-icons/react";

export default function ApiKeys() {
  const [keys, setKeys] = useState([]);
  const [apps, setApps] = useState([]);
  const [orgs, setOrgs] = useState([]);
  const [createOpen, setCreateOpen] = useState(false);
  const [plaintext, setPlaintext] = useState(null); // shown ONCE

  const load = () => api.get("/integrations/keys").then(({ data }) => setKeys(data.items || []));
  useEffect(() => {
    load();
    api.get("/integrations/apps").then(({ data }) => setApps(data.items || []));
    api.get("/organizations").then(({ data }) => setOrgs(data.items || []));
  }, []);

  const revoke = async (id) => {
    if (!window.confirm("Revoke this key? This cannot be undone.")) return;
    await api.post(`/integrations/keys/${id}/revoke`);
    toast.success("Key revoked");
    load();
  };

  const createKey = async (values) => {
    const payload = {
      ...values,
      scopes: (values.scopes || "read:positions,read:transactions").split(",").map(s => s.trim()).filter(Boolean),
    };
    const { data } = await api.post("/integrations/keys", payload);
    setPlaintext({ key: data.api_key_plaintext, label: data.label });
    load();
  };

  const copyPlain = () => {
    navigator.clipboard.writeText(plaintext.key);
    toast.success("Key copied to clipboard");
  };

  return (
    <div data-testid="api-keys-page">
      <PageHeader title="API Keys" subtitle={`${keys.length} keys issued`}
        actions={
          <Button onClick={() => setCreateOpen(true)} data-testid="create-key-btn"
                  className="rounded-full bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white gap-1.5">
            <Plus size={14} weight="bold" /> New Key
          </Button>
        }
      />

      {keys.length === 0 ? <EmptyState title="No keys" /> : (
        <div className="prosper-card overflow-hidden">
          <table className="data-table w-full">
            <thead><tr>
              <th>Label</th>
              <th>Prefix</th>
              <th>Env</th>
              <th>Scopes</th>
              <th>Last Used</th>
              <th>Status</th>
              <th className="text-right">Actions</th>
            </tr></thead>
            <tbody>
              {keys.map((k) => (
                <tr key={k.key_id} data-testid={`key-row-${k.key_id}`}>
                  <td className="text-[var(--fg)]">{k.label}</td>
                  <td><CopyField value={k.key_prefix} /></td>
                  <td><EnvPill env={k.environment} /></td>
                  <td className="text-xs font-mono text-[var(--fg)]">{k.scopes?.join(", ") || "—"}</td>
                  <td className="text-xs font-mono text-[var(--fg-muted)]">{k.last_used_at ? relativeTime(k.last_used_at) : "—"}</td>
                  <td><StatusBadge value={k.status} /></td>
                  <td className="text-right">
                    {k.status === "active" && (
                      <Button size="sm" variant="outline" onClick={() => revoke(k.key_id)}
                              className="h-7 text-xs border-[var(--danger)]/30 text-[var(--danger)] rounded-full"
                              data-testid={`revoke-${k.key_id}`}>Revoke</Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <FormDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        title="Issue New API Key"
        description="A plaintext key will be shown once. Store it securely — it cannot be retrieved later."
        submitLabel="Issue Key"
        onSubmit={createKey}
        testId="create-key-dialog"
        fields={[
          { key: "label", label: "Label", required: true, placeholder: "Production Server" },
          { key: "org_id", label: "Organization", type: "select", required: true,
            options: orgs.map(o => ({ value: o.org_id, label: o.name })) },
          { key: "app_id", label: "API App", type: "select", required: true,
            options: apps.map(a => ({ value: a.app_id, label: `${a.name} (${a.environment})` })) },
          { key: "environment", label: "Environment", type: "select", default: "sandbox",
            options: [{ value: "sandbox", label: "Sandbox" }, { value: "production", label: "Production" }] },
          { key: "scopes", label: "Scopes", default: "read:positions,read:transactions",
            help: "Comma-separated. Common: read:positions, write:transactions, read:funds, read:webhooks." },
        ]}
      />

      {/* One-time plaintext modal */}
      <Dialog open={!!plaintext} onOpenChange={(o) => !o && setPlaintext(null)}>
        <DialogContent className="max-w-lg bg-[var(--surface)] border-[var(--border)] rounded-xl" data-testid="plaintext-modal">
          <DialogHeader>
            <DialogTitle className="font-display flex items-center gap-2">
              <WarningCircle size={18} className="text-[var(--warning)]" weight="fill" />
              Copy this key now
            </DialogTitle>
            <p className="text-sm text-[var(--fg-muted)]">
              This is the <strong>only time</strong> this plaintext key will be shown. Store it in a secret manager (AWS Secrets Manager, HashiCorp Vault, 1Password).
            </p>
          </DialogHeader>
          <div className="space-y-3 pt-2">
            <div className="text-[10px] uppercase tracking-wider text-[var(--fg-muted)]">{plaintext?.label}</div>
            <div className="p-4 bg-[var(--bg)] border border-[var(--border-strong)] rounded-md font-mono text-xs break-all">
              {plaintext?.key}
            </div>
            <Button onClick={copyPlain} data-testid="copy-plaintext-key"
                    className="w-full rounded-full bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white gap-2">
              <Copy size={14} weight="bold" /> Copy key to clipboard
            </Button>
          </div>
          <DialogFooter>
            <Button onClick={() => setPlaintext(null)} className="rounded-full" variant="outline"
                    data-testid="plaintext-dismiss">I've saved it</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
