"use client";
import { useState } from "react";
import { toast } from "sonner";
import {
  KeyRound, Plus, Copy, RotateCw, Trash2, Check,
  ShieldCheck, Activity, AlertTriangle,
} from "lucide-react";
import { PageHeader, Badge } from "@prosper/ui";
import { RefreshButton } from "@/components/PageActions";
import { api } from "@/lib/api";
import { useClientMe } from "@/lib/client-portal";
import { useApiKeys, type ApiKey, type CreatedApiKey } from "@/lib/developer";

export default function ApiKeysPage() {
  const { data: me } = useClientMe();
  const { data, isLoading, mutate } = useApiKeys();
  const keys = data?.items ?? [];

  const isAdmin = me?.user?.role === "client_admin" || me?.user?.role === "super_admin";
  const isProductionOrg = me?.org?.env === "production";

  const [createOpen, setCreateOpen] = useState(false);
  const [reveal, setReveal] = useState<CreatedApiKey | null>(null);

  const onCreate = async (name: string, scope: "sandbox" | "production") => {
    try {
      const res = await api<CreatedApiKey>("/v1/client/api-keys", {
        method: "POST",
        body: JSON.stringify({ name, scope }),
      });
      setCreateOpen(false);
      setReveal(res);
      mutate();
    } catch (err) {
      toast.error((err as Error).message || "Error al crear la key");
    }
  };

  const onRotate = async (k: ApiKey) => {
    if (!window.confirm(`¿Rotar "${k.name}"? La key actual va a dejar de funcionar.`)) return;
    try {
      const res = await api<CreatedApiKey>(`/v1/client/api-keys/${k.key_id}/rotate`,
        { method: "POST" });
      setReveal({ ...res, name: k.name, scope: k.scope });
      mutate();
    } catch (err) {
      toast.error((err as Error).message || "Error al rotar");
    }
  };

  const onRevoke = async (k: ApiKey) => {
    if (!window.confirm(`¿Revocar "${k.name}"? Esta acción no se puede deshacer.`)) return;
    try {
      await api(`/v1/client/api-keys/${k.key_id}`, { method: "DELETE" });
      toast.success(`Key "${k.name}" revocada`);
      mutate();
    } catch (err) {
      toast.error((err as Error).message);
    }
  };

  return (
    <div data-testid="api-keys-page">
      <PageHeader
        breadcrumbs={[{ label: "Inicio", href: "/client" }, { label: "API Keys" }]}
        title="API Keys"
        subtitle="Issue, rotate y revoke. La key plaintext se muestra una sola vez al crearse."
        actions={
          <div className="flex items-center gap-2">
            <RefreshButton onClick={() => mutate()} />
            {isAdmin && (
              <button
                onClick={() => setCreateOpen(true)}
                className="prosper-btn-primary h-9 px-3 text-xs gap-1.5"
                data-testid="apikey-new">
                <Plus size={13} /> Nueva API Key
              </button>
            )}
          </div>
        }
      />

      {!isAdmin && (
        <div className="prosper-card p-4 mb-5 border-warning/30 bg-warning/5 flex items-center gap-3">
          <ShieldCheck size={16} className="text-warning shrink-0" />
          <p className="text-xs text-fg-muted">
            Sólo los <strong>client_admin</strong> de la organización pueden crear, rotar o revocar keys.
          </p>
        </div>
      )}

      {isLoading ? (
        <div className="prosper-card p-8 animate-pulse h-32" />
      ) : keys.length === 0 ? (
        <div className="prosper-card p-10 text-center" data-testid="apikey-empty">
          <KeyRound size={28} className="mx-auto text-fg-subtle mb-2" />
          <h2 className="font-display font-bold text-lg text-fg">Sin keys aún</h2>
          <p className="text-sm text-fg-muted mt-1 max-w-sm mx-auto">
            Generá tu primera key para empezar a integrar Prosper.
          </p>
          {isAdmin && (
            <button
              onClick={() => setCreateOpen(true)}
              className="prosper-btn-primary inline-flex h-10 px-5 mt-4 text-sm gap-2">
              <Plus size={14}/> Crear primera key
            </button>
          )}
        </div>
      ) : (
        <div className="prosper-card overflow-hidden">
          <table className="w-full text-sm" data-testid="apikey-table">
            <thead>
              <tr className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle border-b border-border bg-surface/50">
                <Th>Nombre</Th>
                <Th>Scope</Th>
                <Th>Prefix</Th>
                <Th>Creada</Th>
                <Th>Última usada</Th>
                <Th right>Acciones</Th>
              </tr>
            </thead>
            <tbody>
              {keys.map((k) => (
                <tr key={k.key_id} className="border-b border-border/50 hover:bg-surface-hover"
                    data-testid={`apikey-row-${k.key_id}`}>
                  <Td>
                    <div className="font-display font-semibold text-fg">{k.name}</div>
                  </Td>
                  <Td>
                    <Badge tone={k.scope === "production" ? "danger" : "info"} size="sm">
                      {k.scope}
                    </Badge>
                  </Td>
                  <Td>
                    <code className="text-[11px] font-mono text-fg-muted">
                      {k.prefix}…<span className="opacity-60">****</span>
                    </code>
                  </Td>
                  <Td>
                    <span className="text-xs font-mono text-fg-muted">
                      {new Date(k.created_at).toLocaleDateString()}
                    </span>
                  </Td>
                  <Td>
                    {k.last_used_at ? (
                      <span className="text-xs text-fg-muted">
                        {relativeTime(k.last_used_at)}
                        {k.last_used_ip && (
                          <span className="ml-1 text-fg-subtle font-mono">· {k.last_used_ip}</span>
                        )}
                      </span>
                    ) : (
                      <span className="text-[11px] text-fg-subtle italic">Nunca usada</span>
                    )}
                  </Td>
                  <Td right>
                    {isAdmin && (
                      <div className="flex items-center gap-1 justify-end">
                        <button onClick={() => onRotate(k)}
                          className="prosper-btn-ghost h-8 px-2 text-[11px] gap-1"
                          data-testid={`apikey-rotate-${k.key_id}`}>
                          <RotateCw size={11}/> Rotar
                        </button>
                        <button onClick={() => onRevoke(k)}
                          className="prosper-btn-ghost h-8 px-2 text-[11px] gap-1 text-danger hover:bg-danger/10"
                          data-testid={`apikey-revoke-${k.key_id}`}>
                          <Trash2 size={11}/> Revocar
                        </button>
                      </div>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Stats footer */}
      {keys.length > 0 && (
        <div className="mt-4 flex items-center gap-4 text-[11px] font-mono text-fg-subtle">
          <span className="inline-flex items-center gap-1">
            <Activity size={11}/> {keys.length} key{keys.length === 1 ? "" : "s"}
          </span>
          <span className="inline-flex items-center gap-1">
            <Badge tone="info" size="sm">sandbox</Badge>
            <span className="text-fg-muted">{keys.filter((k) => k.scope === "sandbox").length}</span>
          </span>
          {keys.some((k) => k.scope === "production") && (
            <span className="inline-flex items-center gap-1">
              <Badge tone="danger" size="sm">production</Badge>
              <span className="text-fg-muted">{keys.filter((k) => k.scope === "production").length}</span>
            </span>
          )}
        </div>
      )}

      {createOpen && (
        <CreateModal
          onCancel={() => setCreateOpen(false)}
          onCreate={onCreate}
          productionLocked={!isProductionOrg}
        />
      )}
      {reveal && <RevealModal data={reveal} onClose={() => setReveal(null)} />}
    </div>
  );
}

function CreateModal({ onCancel, onCreate, productionLocked }:
  { onCancel: () => void;
    onCreate: (name: string, scope: "sandbox" | "production") => void;
    productionLocked: boolean }) {
  const [name, setName] = useState("");
  const [scope, setScope] = useState<"sandbox" | "production">("sandbox");
  return (
    <Modal onClose={onCancel} testid="apikey-create-modal">
      <h2 className="font-display font-bold text-lg text-fg flex items-center gap-2">
        <KeyRound size={16}/> Nueva API Key
      </h2>
      <p className="text-xs text-fg-muted mt-1 mb-4">
        Dale un nombre legible (ej. "backend prod", "widget", "playground").
      </p>

      <label className="block mb-3">
        <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-1">
          Nombre *
        </div>
        <input value={name} onChange={(e) => setName(e.target.value)}
          maxLength={50}
          className="prosper-input w-full h-10 text-sm"
          placeholder="backend prod"
          data-testid="apikey-name" />
      </label>

      <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-2">Scope</div>
      <div className="grid grid-cols-2 gap-2 mb-5">
        {(["sandbox", "production"] as const).map((s) => (
          <button key={s} type="button"
            disabled={s === "production" && productionLocked}
            onClick={() => setScope(s)}
            className={`p-3 rounded border text-left transition-all
                        ${scope === s
                          ? "border-primary bg-primary/5 ring-1 ring-primary"
                          : "border-border hover:bg-surface-hover"}
                        ${s === "production" && productionLocked ? "opacity-40 cursor-not-allowed" : ""}`}
            data-testid={`apikey-scope-${s}`}>
            <div className="text-sm font-display font-bold text-fg capitalize">{s}</div>
            <div className="text-[10px] text-fg-muted">
              {s === "sandbox" ? "Para testing — datos simulados"
                : productionLocked
                  ? "Bloqueado · tu org está en sandbox"
                  : "Operaciones reales"}
            </div>
          </button>
        ))}
      </div>

      <div className="flex gap-2">
        <button onClick={onCancel}
          className="prosper-btn-ghost flex-1 h-11 text-sm" data-testid="apikey-cancel">
          Cancelar
        </button>
        <button onClick={() => onCreate(name, scope)}
          disabled={!name.trim()}
          className="prosper-btn-primary flex-1 h-11 text-sm disabled:opacity-40"
          data-testid="apikey-create">
          Crear
        </button>
      </div>
    </Modal>
  );
}

function RevealModal({ data, onClose }: { data: CreatedApiKey; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard.writeText(data.plaintext);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <Modal onClose={onClose} testid="apikey-reveal-modal" wide>
      <div className="flex items-center gap-2 mb-3">
        <AlertTriangle size={16} className="text-warning"/>
        <h2 className="font-display font-bold text-lg text-fg">
          Guardá esta key ahora
        </h2>
      </div>
      <p className="text-xs text-fg-muted mb-4">
        Esta es la única vez que vas a ver la key completa.
        Si la perdés, no la vas a poder recuperar — tendrás que rotar y reemplazar.
      </p>

      <div className="rounded-lg border border-border bg-bg p-3 flex items-center gap-2 mb-4"
           data-testid="apikey-reveal-secret">
        <code className="flex-1 text-sm font-mono text-fg break-all">
          {data.plaintext}
        </code>
        <button onClick={copy}
          className="prosper-btn-primary h-9 px-3 text-xs gap-1.5 shrink-0"
          data-testid="apikey-copy">
          {copied ? <><Check size={12}/> Copiado</> : <><Copy size={12}/> Copiar</>}
        </button>
      </div>

      <div className="text-[11px] text-fg-subtle font-mono mb-5 space-y-1">
        <div>nombre · <span className="text-fg-muted">{data.name}</span></div>
        <div>scope · <span className="text-fg-muted">{data.scope}</span></div>
        <div>prefix · <span className="text-fg-muted">{data.prefix}</span></div>
      </div>

      <button onClick={onClose}
        className="prosper-btn-primary w-full h-11 text-sm"
        data-testid="apikey-reveal-done">
        Entiendo, llevarme al listado
      </button>
    </Modal>
  );
}

function Modal({ children, onClose, testid, wide }:
  { children: React.ReactNode; onClose: () => void; testid: string; wide?: boolean }) {
  return (
    <div className="fixed inset-0 bg-bg/70 backdrop-blur-sm z-50 grid place-items-center p-4"
         onClick={onClose}
         data-testid={testid}>
      <div className={`prosper-card p-6 w-full ${wide ? "max-w-lg" : "max-w-md"}`}
           onClick={(e) => e.stopPropagation()}>
        {children}
      </div>
    </div>
  );
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <th className={`px-4 py-2 ${right ? "text-right" : "text-left"} font-normal`}>{children}</th>;
}
function Td({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <td className={`px-4 py-3 ${right ? "text-right" : "text-left"}`}>{children}</td>;
}

function relativeTime(iso: string): string {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60)        return `hace ${Math.floor(diff)}s`;
  if (diff < 3600)      return `hace ${Math.floor(diff / 60)}m`;
  if (diff < 86400)     return `hace ${Math.floor(diff / 3600)}h`;
  return `hace ${Math.floor(diff / 86400)}d`;
}
