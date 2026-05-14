"use client";
import { useState } from "react";
import { toast } from "sonner";
import {
  Webhook as WebhookIcon, Plus, Copy, Check, Trash2, Play,
  AlertTriangle, Pause, Eye, EyeOff, ChevronDown, ChevronUp,
} from "lucide-react";
import { PageHeader, Badge } from "@prosper/ui";
import { RefreshButton } from "@/components/PageActions";
import { api } from "@/lib/api";
import { useClientMe } from "@/lib/client-portal";
import { useWebhooks, useDeliveries, type Webhook } from "@/lib/developer";

export default function WebhooksPage() {
  const { data: me } = useClientMe();
  const { data, mutate } = useWebhooks();
  const items = data?.items ?? [];
  const events = data?.available_events ?? [];
  const isAdmin = me?.user?.role === "client_admin" || me?.user?.role === "super_admin";

  const [createOpen, setCreateOpen] = useState(false);
  const [createdSecret, setCreatedSecret] = useState<{ webhook: Webhook; secret: string } | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const doCreate = async (form: { url: string; events: string[]; description: string }) => {
    try {
      const res = await api<{ webhook: Webhook; secret: string }>(
        "/v1/client/webhooks",
        { method: "POST", body: JSON.stringify(form) });
      setCreateOpen(false);
      setCreatedSecret({ webhook: res.webhook, secret: res.secret });
      mutate();
    } catch (err) {
      toast.error((err as Error).message);
    }
  };

  const togglePause = async (w: Webhook) => {
    try {
      await api(`/v1/client/webhooks/${w.webhook_id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: w.status === "paused" ? "active" : "paused" }),
      });
      mutate();
    } catch (err) { toast.error((err as Error).message); }
  };

  const onDelete = async (w: Webhook) => {
    if (!window.confirm(`¿Eliminar webhook ${w.url}?`)) return;
    try {
      await api(`/v1/client/webhooks/${w.webhook_id}`, { method: "DELETE" });
      mutate();
    } catch (err) { toast.error((err as Error).message); }
  };

  const onTest = async (w: Webhook) => {
    try {
      const res = await api<{ ok: boolean; delivery: { http_code?: number; error?: string } }>(
        `/v1/client/webhooks/${w.webhook_id}/test`,
        { method: "POST" });
      if (res.ok) toast.success(`Test OK · HTTP ${res.delivery.http_code}`);
      else toast.error(`Test falló · ${res.delivery.error || res.delivery.http_code}`);
      mutate();
    } catch (err) { toast.error((err as Error).message); }
  };

  return (
    <div data-testid="webhooks-page">
      <PageHeader
        breadcrumbs={[{ label: "Client", href: "/client" }, { label: "Webhooks" }]}
        kicker="Phase 11 · Developer"
        title="Webhooks"
        subtitle="Recibí eventos de tu actividad en tiempo real. Cada delivery viene firmado con HMAC."
        actions={
          <div className="flex items-center gap-2">
            <RefreshButton onClick={() => mutate()} />
            {isAdmin && (
              <button onClick={() => setCreateOpen(true)}
                className="prosper-btn-primary h-9 px-3 text-xs gap-1.5"
                data-testid="webhook-new">
                <Plus size={13}/> Nuevo endpoint
              </button>
            )}
          </div>
        }
      />

      {items.length === 0 ? (
        <div className="prosper-card p-10 text-center" data-testid="webhook-empty">
          <WebhookIcon size={28} className="mx-auto text-fg-subtle mb-2" />
          <h2 className="font-display font-bold text-lg text-fg">Sin endpoints registrados</h2>
          <p className="text-sm text-fg-muted mt-1 max-w-sm mx-auto">
            Registrá una URL HTTPS para recibir eventos como onramp.confirmed, redeem.confirmed, etc.
          </p>
        </div>
      ) : (
        <div className="space-y-3" data-testid="webhook-list">
          {items.map((w) => (
            <WebhookCard
              key={w.webhook_id}
              w={w}
              isAdmin={isAdmin}
              expanded={expandedId === w.webhook_id}
              onToggle={() => setExpandedId(expandedId === w.webhook_id ? null : w.webhook_id)}
              onPause={() => togglePause(w)}
              onDelete={() => onDelete(w)}
              onTest={() => onTest(w)}
            />
          ))}
        </div>
      )}

      {createOpen && (
        <CreateModal
          events={events}
          onClose={() => setCreateOpen(false)}
          onCreate={doCreate}
        />
      )}
      {createdSecret && (
        <SecretModal secret={createdSecret.secret} onClose={() => setCreatedSecret(null)} />
      )}
    </div>
  );
}

function WebhookCard({ w, isAdmin, expanded, onToggle, onPause, onDelete, onTest }:
  { w: Webhook; isAdmin: boolean; expanded: boolean;
    onToggle: () => void; onPause: () => void; onDelete: () => void; onTest: () => void }) {
  const tone = w.status === "active" ? "success"
              : w.status === "paused" ? "warning"
              : "danger";
  const lastTone = w.last_status === "ok" ? "success"
                 : w.last_status === "failed" ? "danger"
                 : "default";
  return (
    <div className="prosper-card p-4" data-testid={`webhook-${w.webhook_id}`}>
      <div className="flex items-start gap-3 flex-wrap">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <code className="text-sm font-mono text-fg break-all">{w.url}</code>
            <Badge tone={tone} size="sm">{w.status}</Badge>
            {w.last_status && (
              <Badge tone={lastTone} size="sm">last · {w.last_status}</Badge>
            )}
            {w.fail_count > 0 && (
              <Badge tone="danger" size="sm">fails · {w.fail_count}</Badge>
            )}
          </div>
          <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mt-1.5">
            {w.events.length} event{w.events.length === 1 ? "" : "s"} · creado {new Date(w.created_at).toLocaleDateString()}
            {w.last_delivery_at && (
              <span> · último delivery {new Date(w.last_delivery_at).toLocaleString()}</span>
            )}
          </div>
          <div className="flex flex-wrap gap-1 mt-2">
            {w.events.map((e) => (
              <span key={e} className="text-[10px] font-mono px-2 py-0.5 rounded
                                       bg-bg-muted text-fg-muted border border-border">
                {e}
              </span>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-1">
          {isAdmin && (
            <>
              <button onClick={onTest}
                className="prosper-btn-ghost h-8 px-2 text-[11px] gap-1"
                data-testid={`webhook-test-${w.webhook_id}`}>
                <Play size={11}/> Test
              </button>
              <button onClick={onPause}
                className="prosper-btn-ghost h-8 px-2 text-[11px] gap-1"
                data-testid={`webhook-toggle-${w.webhook_id}`}>
                <Pause size={11}/> {w.status === "paused" ? "Activar" : "Pausar"}
              </button>
              <button onClick={onDelete}
                className="prosper-btn-ghost h-8 px-2 text-[11px] gap-1 text-danger hover:bg-danger/10"
                data-testid={`webhook-delete-${w.webhook_id}`}>
                <Trash2 size={11}/>
              </button>
            </>
          )}
          <button onClick={onToggle}
            className="prosper-btn-ghost h-8 px-2 text-[11px] gap-1"
            data-testid={`webhook-expand-${w.webhook_id}`}>
            {expanded ? <ChevronUp size={11}/> : <ChevronDown size={11}/>}
            Deliveries
          </button>
        </div>
      </div>

      {expanded && <DeliveryLog webhookId={w.webhook_id} />}
    </div>
  );
}

function DeliveryLog({ webhookId }: { webhookId: string }) {
  const { data, isLoading } = useDeliveries(webhookId);
  const rows = data?.items ?? [];
  return (
    <div className="mt-3 pt-3 border-t border-border" data-testid={`deliveries-${webhookId}`}>
      <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-2">
        Últimos deliveries
      </div>
      {isLoading ? (
        <div className="h-16 animate-pulse bg-bg-muted rounded" />
      ) : rows.length === 0 ? (
        <p className="text-xs text-fg-subtle py-2">Sin entregas aún.</p>
      ) : (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
              <th className="px-2 py-1 text-left font-normal">Timestamp</th>
              <th className="px-2 py-1 text-left font-normal">Event</th>
              <th className="px-2 py-1 text-left font-normal">HTTP</th>
              <th className="px-2 py-1 text-left font-normal">Retry</th>
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 10).map((d) => (
              <tr key={d.delivery_id} className="border-t border-border/50"
                  data-testid={`delivery-${d.delivery_id}`}>
                <td className="px-2 py-1 font-mono text-fg-muted">
                  {new Date(d.ts).toLocaleTimeString()}
                </td>
                <td className="px-2 py-1 font-mono">{d.event}</td>
                <td className="px-2 py-1">
                  {d.http_code ? (
                    <Badge tone={d.http_code < 300 ? "success" : "danger"} size="sm">
                      {d.http_code}
                    </Badge>
                  ) : (
                    <Badge tone="danger" size="sm">err</Badge>
                  )}
                </td>
                <td className="px-2 py-1 font-mono text-fg-subtle">{d.retry_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function CreateModal({ events, onClose, onCreate }:
  { events: string[]; onClose: () => void;
    onCreate: (f: { url: string; events: string[]; description: string }) => void }) {
  const [url, setUrl] = useState("https://");
  const [desc, setDesc] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const toggle = (e: string) =>
    setPicked((p) => p.includes(e) ? p.filter((x) => x !== e) : [...p, e]);
  return (
    <Modal onClose={onClose} testid="webhook-create-modal">
      <h2 className="font-display font-bold text-lg text-fg flex items-center gap-2">
        <WebhookIcon size={16}/> Nuevo endpoint
      </h2>

      <label className="block mt-3">
        <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-1">
          URL (HTTPS)
        </div>
        <input value={url} onChange={(e) => setUrl(e.target.value)}
          className="prosper-input w-full h-10 text-sm font-mono"
          placeholder="https://app.mio.com/webhooks/prosper"
          data-testid="webhook-url" />
      </label>

      <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mt-3 mb-2">
        Events ({picked.length} elegidos)
      </div>
      <div className="grid grid-cols-2 gap-1.5 max-h-48 overflow-y-auto pr-1">
        {events.map((e) => (
          <label key={e} className={`flex items-center gap-2 px-2 py-1.5 rounded text-xs cursor-pointer
                                       ${picked.includes(e) ? "bg-primary/10 text-primary" : "hover:bg-surface-hover"}`}
                  data-testid={`webhook-event-${e}`}>
            <input type="checkbox" checked={picked.includes(e)} onChange={() => toggle(e)}
              className="h-3.5 w-3.5 rounded border-border text-primary" />
            <code className="font-mono">{e}</code>
          </label>
        ))}
      </div>

      <label className="block mt-3">
        <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-1">
          Descripción (opcional)
        </div>
        <input value={desc} onChange={(e) => setDesc(e.target.value)}
          className="prosper-input w-full h-10 text-sm"
          data-testid="webhook-desc" />
      </label>

      <div className="flex gap-2 mt-5">
        <button onClick={onClose}
          className="prosper-btn-ghost flex-1 h-11 text-sm">Cancelar</button>
        <button onClick={() => onCreate({ url, events: picked, description: desc })}
          disabled={!url.startsWith("https://") || picked.length === 0}
          className="prosper-btn-primary flex-1 h-11 text-sm disabled:opacity-40"
          data-testid="webhook-create">
          Crear endpoint
        </button>
      </div>
    </Modal>
  );
}

function SecretModal({ secret, onClose }: { secret: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const [show, setShow] = useState(true);
  const copy = async () => {
    await navigator.clipboard.writeText(secret);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <Modal onClose={onClose} testid="webhook-secret-modal" wide>
      <div className="flex items-center gap-2 mb-3">
        <AlertTriangle size={16} className="text-warning"/>
        <h2 className="font-display font-bold text-lg text-fg">HMAC secret</h2>
      </div>
      <p className="text-xs text-fg-muted mb-4">
        Usá este secret para verificar la firma de cada delivery (header <code>X-Prosper-Signature</code>).
        Se muestra una sola vez.
      </p>
      <div className="rounded-lg border border-border bg-bg p-3 flex items-center gap-2 mb-4"
           data-testid="webhook-secret-value">
        <code className="flex-1 text-sm font-mono text-fg break-all">
          {show ? secret : "•".repeat(Math.min(40, secret.length))}
        </code>
        <button onClick={() => setShow(!show)}
          className="prosper-btn-ghost h-9 px-2 text-xs"
          data-testid="webhook-secret-toggle">
          {show ? <EyeOff size={12}/> : <Eye size={12}/>}
        </button>
        <button onClick={copy}
          className="prosper-btn-primary h-9 px-3 text-xs gap-1.5"
          data-testid="webhook-secret-copy">
          {copied ? <><Check size={12}/> Copiado</> : <><Copy size={12}/> Copiar</>}
        </button>
      </div>
      <button onClick={onClose}
        className="prosper-btn-primary w-full h-11 text-sm">Entendido</button>
    </Modal>
  );
}

function Modal({ children, onClose, testid, wide }:
  { children: React.ReactNode; onClose: () => void; testid: string; wide?: boolean }) {
  return (
    <div className="fixed inset-0 bg-bg/70 backdrop-blur-sm z-50 grid place-items-center p-4"
         onClick={onClose} data-testid={testid}>
      <div className={`prosper-card p-6 w-full ${wide ? "max-w-xl" : "max-w-lg"}`}
           onClick={(e) => e.stopPropagation()}>
        {children}
      </div>
    </div>
  );
}
