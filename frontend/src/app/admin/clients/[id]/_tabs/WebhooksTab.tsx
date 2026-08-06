"use client";
import { useState } from "react";
import { toast } from "sonner";
import { Plus, Trash2, Eye, Send, ChevronDown } from "lucide-react";
import { Badge } from "@prosper/ui";
import {
  useWebhooks, createWebhook, deleteWebhook,
  revealWebhookSecret, testWebhook, useWebhookDeliveries,
} from "@/lib/admin-clients";
import { cn, fmtDate } from "@/lib/utils";

export default function WebhooksTab({ orgId }: { orgId: string }) {
  const swr = useWebhooks(orgId);
  const [showNew, setShowNew] = useState(false);
  const [draft, setDraft] = useState({ url: "", events: [] as string[] });
  const [revealed, setRevealed] = useState<{ id: string; secret: string } | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  const events = swr.data?.available_events ?? [];

  const create = async () => {
    if (!draft.url || draft.events.length === 0) {
      return toast.error("URL + al menos 1 event");
    }
    try {
      const res = await createWebhook(orgId, draft);
      setRevealed({ id: res.webhook.webhook_id, secret: res.secret });
      setDraft({ url: "", events: [] }); setShowNew(false);
      await swr.mutate();
    } catch (e: any) { toast.error(e?.message || "Failed"); }
  };
  const reveal = async (id: string) => {
    try {
      const res = await revealWebhookSecret(orgId, id);
      setRevealed({ id, secret: res.secret });
      setTimeout(() => setRevealed(null), 30_000);
    } catch (e: any) { toast.error(e?.message || "Failed"); }
  };
  const test = async (id: string) => {
    toast.info("Enviando test payload…");
    try {
      const res: any = await testWebhook(orgId, id);
      if (res.ok) toast.success(`Test OK · http ${res.delivery.http_code}`);
      else        toast.error(`Test failed · ${res.delivery.http_code || res.delivery.error}`);
      await swr.mutate();
    } catch (e: any) { toast.error(e?.message || "Failed"); }
  };
  const del = async (id: string) => {
    if (!confirm("Eliminar este webhook?")) return;
    try { await deleteWebhook(orgId, id); await swr.mutate(); toast.success("Deleted"); }
    catch (e: any) { toast.error(e?.message || "Failed"); }
  };

  return (
    <div data-testid="tab-content-webhooks" className="space-y-3">
      <div className="flex justify-end">
        <button onClick={() => setShowNew((v) => !v)} data-testid="webhook-new-btn"
          className="prosper-btn-primary h-9 text-xs gap-1.5">
          <Plus size={12}/> Nuevo endpoint
        </button>
      </div>
      {showNew && (
        <div className="prosper-card p-4 space-y-3">
          <input placeholder="https://cliente.com/prosper-webhook" value={draft.url}
            onChange={(e) => setDraft({...draft, url: e.target.value})}
            data-testid="webhook-url"
            className="w-full h-9 px-3 rounded border border-border bg-surface font-mono text-xs"/>
          <div>
            <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-1.5">Events</div>
            <div className="flex flex-wrap gap-1.5">
              {events.map((e) => {
                const on = draft.events.includes(e);
                return (
                  <button key={e} onClick={() =>
                    setDraft({...draft,
                      events: on ? draft.events.filter((x) => x !== e) : [...draft.events, e]})}
                    data-testid={`webhook-evt-${e}`}
                    className={cn("h-7 px-2.5 rounded-full text-[10px] font-mono",
                      on ? "bg-fg text-bg" : "bg-surface text-fg-muted hover:text-fg border border-border")}>
                    {e}
                  </button>
                );
              })}
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <button onClick={() => setShowNew(false)} className="prosper-btn-ghost h-9 text-xs">Cancel</button>
            <button onClick={create} data-testid="webhook-create"
              className="prosper-btn-primary h-9 text-xs">Crear y generar secret</button>
          </div>
        </div>
      )}

      {revealed && (
        <div className="prosper-card border-warning/40 bg-warning/5 p-3"
             data-testid="webhook-secret-banner">
          <div className="text-[10px] font-mono uppercase tracking-wider text-warning mb-1">
            HMAC secret · 30s
          </div>
          <code className="text-xs font-mono break-all"
                data-testid="webhook-secret-value">{revealed.secret}</code>
        </div>
      )}

      <div className="space-y-2">
        {(swr.data?.items ?? []).map((w: any) => (
          <div key={w.webhook_id} className="prosper-card p-4" data-testid={`webhook-row-${w.webhook_id}`}>
            <div className="flex items-center justify-between gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <code className="text-xs font-mono text-fg truncate">{w.url}</code>
                  <Badge tone={w.last_status === "ok" ? "success"
                                : w.last_status === "failed" ? "danger" : "warning"} size="sm">
                    {w.last_status || w.status}
                  </Badge>
                  {w.fail_count > 0 && (
                    <span className="text-[10px] font-mono text-danger">fails: {w.fail_count}</span>
                  )}
                </div>
                <div className="flex flex-wrap gap-1 mt-1.5">
                  {w.events.map((e: string) => (
                    <span key={e} className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-surface-hover text-fg-muted">
                      {e}
                    </span>
                  ))}
                </div>
                <div className="text-[10px] text-fg-subtle font-mono mt-1.5">
                  secret prefix: {w.secret_prefix}…
                  {w.last_delivery_at && <> · last delivery {fmtDate(w.last_delivery_at)}</>}
                </div>
              </div>
              <div className="flex items-center gap-1.5">
                <button onClick={() => reveal(w.webhook_id)}
                  data-testid={`webhook-reveal-${w.webhook_id}`}
                  className="prosper-btn-ghost h-8 px-2 text-[10px] gap-1"><Eye size={11}/> secret</button>
                <button onClick={() => test(w.webhook_id)}
                  data-testid={`webhook-test-${w.webhook_id}`}
                  className="prosper-btn-ghost h-8 px-2 text-[10px] gap-1"><Send size={11}/> test</button>
                <button onClick={() => setExpanded(expanded === w.webhook_id ? null : w.webhook_id)}
                  data-testid={`webhook-expand-${w.webhook_id}`}
                  className="prosper-btn-ghost h-8 px-2 text-[10px] gap-1"><ChevronDown size={11}/> log</button>
                <button onClick={() => del(w.webhook_id)}
                  data-testid={`webhook-delete-${w.webhook_id}`}
                  className="prosper-btn-ghost h-8 px-2 text-[10px] text-danger gap-1"><Trash2 size={11}/></button>
              </div>
            </div>
            {expanded === w.webhook_id && (
              <DeliveryLog orgId={orgId} whId={w.webhook_id}/>
            )}
          </div>
        ))}
        {(swr.data?.items ?? []).length === 0 && (
          <div className="text-fg-subtle text-xs py-6 text-center italic">Sin webhooks registrados.</div>
        )}
      </div>
    </div>
  );
}

function DeliveryLog({ orgId, whId }: { orgId: string; whId: string }) {
  const swr = useWebhookDeliveries(orgId, whId);
  return (
    <div className="mt-3 pt-3 border-t border-border" data-testid={`webhook-deliveries-${whId}`}>
      <table className="w-full text-[11px]">
        <thead className="text-[9px] font-mono uppercase tracking-wider text-fg-subtle">
          <tr className="border-b border-border">
            <th className="text-left py-1.5">When</th>
            <th className="text-left py-1.5">Event</th>
            <th className="text-right py-1.5">HTTP</th>
            <th className="text-right py-1.5">Retry</th>
          </tr>
        </thead>
        <tbody>
          {(swr.data?.items ?? []).map((d: any) => (
            <tr key={d.delivery_id} className="border-b border-border">
              <td className="py-1.5 font-mono">{fmtDate(d.ts)}</td>
              <td className="py-1.5">{d.event}</td>
              <td className="py-1.5 text-right font-mono">
                {d.http_code ? (
                  <span className={cn(d.http_code >= 200 && d.http_code < 300 ? "text-success" : "text-danger")}>
                    {d.http_code}
                  </span>
                ) : <span className="text-danger">err</span>}
              </td>
              <td className="py-1.5 text-right font-mono">{d.retry_count}</td>
            </tr>
          ))}
          {(swr.data?.items ?? []).length === 0 && (
            <tr><td colSpan={4} className="py-3 text-center text-fg-subtle italic">
              Sin deliveries todavía. Probá "test" para mandar un payload.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
