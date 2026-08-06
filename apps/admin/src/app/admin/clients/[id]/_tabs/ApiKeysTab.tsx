"use client";
import { useState } from "react";
import { toast } from "sonner";
import { Plus, Trash2, RefreshCw, Copy, AlertTriangle } from "lucide-react";
import { Badge } from "@prosper/ui";
import {
  useApiKeys, createApiKey, rotateApiKey, revokeApiKey,
} from "@/lib/admin-clients";
import { cn, fmtDate } from "@/lib/utils";

export default function ApiKeysTab({ orgId }: { orgId: string }) {
  const swr = useApiKeys(orgId);
  const [show, setShow] = useState(false);
  const [name, setName] = useState("");
  const [scope, setScope] = useState<"sandbox" | "production">("sandbox");
  const [reveal, setReveal] = useState<{ plaintext: string; keyId: string } | null>(null);

  const create = async () => {
    if (!name.trim()) return toast.error("Nombre requerido");
    try {
      const res = await createApiKey(orgId, { name, scope });
      setReveal({ plaintext: res.plaintext, keyId: res.key_id });
      setName(""); setShow(false);
      await swr.mutate();
    } catch (e: any) { toast.error(e?.message || "Failed"); }
  };
  const rotate = async (keyId: string) => {
    if (!confirm("¿Rotar esta key? La actual deja de funcionar.")) return;
    try {
      const res = await rotateApiKey(orgId, keyId);
      setReveal({ plaintext: res.plaintext, keyId });
      await swr.mutate();
    } catch (e: any) { toast.error(e?.message || "Failed"); }
  };
  const revoke = async (keyId: string) => {
    if (!confirm("¿Revocar esta key permanentemente?")) return;
    try { await revokeApiKey(orgId, keyId); await swr.mutate(); toast.success("Revoked"); }
    catch (e: any) { toast.error(e?.message || "Failed"); }
  };

  return (
    <div data-testid="tab-content-api-keys" className="space-y-3">
      <div className="flex justify-end">
        <button onClick={() => setShow((v) => !v)} data-testid="apikey-new-btn"
          className="prosper-btn-primary h-9 text-xs gap-1.5"><Plus size={12}/> Nueva API key</button>
      </div>
      {show && (
        <div className="prosper-card p-4 grid grid-cols-3 gap-3 items-end">
          <input placeholder="Nombre (ej. 'Production backend')" value={name}
            onChange={(e) => setName(e.target.value)}
            data-testid="apikey-name"
            className="h-9 px-3 rounded border border-border bg-surface text-xs col-span-2"/>
          <select value={scope} onChange={(e) => setScope(e.target.value as any)}
            data-testid="apikey-scope"
            className="h-9 px-3 rounded border border-border bg-surface text-xs">
            <option value="sandbox">sandbox</option>
            <option value="production">production</option>
          </select>
          <button onClick={create} data-testid="apikey-create"
            className="prosper-btn-primary h-9 text-xs col-span-3">Crear y generar plaintext</button>
        </div>
      )}

      {reveal && (
        <div className="prosper-card border-warning/40 bg-warning/5 p-4"
             data-testid="apikey-plaintext-banner">
          <div className="flex items-start gap-2">
            <AlertTriangle size={14} className="text-warning shrink-0 mt-0.5"/>
            <div className="flex-1">
              <div className="text-[10px] font-mono uppercase tracking-wider text-warning mb-1">
                Plaintext visible solo esta vez · guardalo ahora
              </div>
              <div className="flex items-center gap-2">
                <code className="text-xs font-mono bg-surface px-3 py-1.5 rounded border border-border flex-1
                                  break-all" data-testid="apikey-plaintext-value">{reveal.plaintext}</code>
                <button onClick={() => navigator.clipboard?.writeText(reveal.plaintext).then(() => toast.success("Copiado"))}
                  data-testid="apikey-plaintext-copy"
                  className="prosper-btn-ghost h-8 px-3 text-xs gap-1.5">
                  <Copy size={11}/> Copy
                </button>
                <button onClick={() => setReveal(null)}
                  data-testid="apikey-plaintext-dismiss"
                  className="prosper-btn-ghost h-8 px-2 text-xs">Dismiss</button>
              </div>
            </div>
          </div>
        </div>
      )}

      <table className="w-full text-xs">
        <thead className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
          <tr className="border-b border-border">
            <th className="text-left py-2">Name</th>
            <th className="text-left py-2">Prefix</th>
            <th className="text-left py-2">Scope</th>
            <th className="text-left py-2">Status</th>
            <th className="text-left py-2">Last used</th>
            <th className="text-left py-2 w-32">Acciones</th>
          </tr>
        </thead>
        <tbody>
          {(swr.data?.items ?? []).map((k: any) => (
            <tr key={k.key_id} className="border-b border-border" data-testid={`apikey-row-${k.key_id}`}>
              <td className="py-2">{k.name}</td>
              <td className="py-2 font-mono">{k.prefix}…</td>
              <td className="py-2"><Badge tone={k.scope === "production" ? "danger" : "warning"} size="sm">{k.scope}</Badge></td>
              <td className="py-2"><Badge tone={k.status === "active" ? "success" : "danger"} size="sm">{k.status}</Badge></td>
              <td className="py-2 font-mono text-[10px]">{k.last_used_at ? fmtDate(k.last_used_at) : "—"}</td>
              <td className="py-2 flex gap-1.5">
                <button onClick={() => rotate(k.key_id)}
                  data-testid={`apikey-rotate-${k.key_id}`}
                  className="text-[10px] text-primary hover:underline inline-flex items-center gap-1">
                  <RefreshCw size={9}/>rotate
                </button>
                <button onClick={() => revoke(k.key_id)}
                  data-testid={`apikey-revoke-${k.key_id}`}
                  className="text-[10px] text-danger hover:underline inline-flex items-center gap-1">
                  <Trash2 size={9}/>revoke
                </button>
              </td>
            </tr>
          ))}
          {(swr.data?.items ?? []).length === 0 && (
            <tr><td colSpan={6} className="py-8 text-center text-fg-subtle italic">
              Sin API keys creadas todavía.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
