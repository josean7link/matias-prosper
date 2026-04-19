import { useEffect, useState } from "react";
import api from "@/lib/api";
import { PageHeader, StatusBadge, EnvPill, CopyField, EmptyState } from "@/components/common";
import { fmtDate, relativeTime } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";

export default function ApiKeys() {
  const [keys, setKeys] = useState([]);
  const load = () => api.get("/integrations/keys").then(({ data }) => setKeys(data.items || []));
  useEffect(() => { load(); }, []);

  const revoke = async (id) => {
    if (!window.confirm("Revoke this key? This cannot be undone.")) return;
    await api.post(`/integrations/keys/${id}/revoke`);
    toast.success("Key revoked");
    load();
  };

  return (
    <div data-testid="api-keys-page">
      <PageHeader title="API Keys" subtitle={`${keys.length} keys issued`} />
      {keys.length === 0 ? <EmptyState title="No keys" /> : (
        <div className="prosper-card overflow-hidden">
          <table className="data-table w-full">
            <thead><tr>
              <th className="text-left px-4 py-3">Label</th>
              <th className="text-left px-4 py-3">Prefix</th>
              <th className="text-left px-4 py-3">Env</th>
              <th className="text-left px-4 py-3">Scopes</th>
              <th className="text-left px-4 py-3">Last Used</th>
              <th className="text-left px-4 py-3">Status</th>
              <th className="text-right px-4 py-3">Actions</th>
            </tr></thead>
            <tbody>
              {keys.map((k) => (
                <tr key={k.key_id} data-testid={`key-row-${k.key_id}`}>
                  <td className="px-4 py-3 text-white">{k.label}</td>
                  <td className="px-4 py-3"><CopyField value={k.key_prefix} /></td>
                  <td className="px-4 py-3"><EnvPill env={k.environment} /></td>
                  <td className="px-4 py-3 text-xs font-mono text-[#ccc]">{k.scopes?.join(", ") || "—"}</td>
                  <td className="px-4 py-3 text-xs font-mono text-[#888]">{k.last_used_at ? relativeTime(k.last_used_at) : "—"}</td>
                  <td className="px-4 py-3"><StatusBadge value={k.status} /></td>
                  <td className="px-4 py-3 text-right">
                    {k.status === "active" && (
                      <Button size="sm" variant="outline" onClick={() => revoke(k.key_id)}
                              className="h-7 text-xs border-[#FF3D00]/30 text-[#FF3D00] rounded-sm"
                              data-testid={`revoke-${k.key_id}`}>Revoke</Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
