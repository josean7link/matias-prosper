"use client";
import { useState } from "react";
import { useTranslations } from "next-intl";
import { Badge, PageHeader } from "@prosper/ui";
import {
  Activity, Search, RefreshCw, ShieldCheck, ShieldOff, GitCompareArrows,
} from "lucide-react";
import {
  useAdminWebhooks, useWebhookDeliveries,
  type WebhookEvent,
} from "@/lib/admin-ramp";

/** Phase 16 · E — /admin/rampa/webhooks
 *  DB events + delivery cross-check with Andes. */
export default function RampWebhooksPage() {
  const tH = useTranslations("admin.headers");
  const tA = useTranslations("admin");
  const [type, setType]     = useState("");
  const [processed, setP]   = useState<"" | "true" | "false">("");
  const [sigValid, setSig]  = useState<"" | "true" | "false">("");
  const qs = "?" + new URLSearchParams({
    ...(type ? { event_type: type } : {}),
    ...(processed ? { processed } : {}),
    ...(sigValid ? { signature_valid: sigValid } : {}),
    limit: "200",
  }).toString();
  const list = useAdminWebhooks(qs);
  const deliv = useWebhookDeliveries();

  return (
    <div className="space-y-6">
      <PageHeader
        crumbs={[{ label: tA("breadcrumb_admin") }, { label: tH("rampa_label") }, { label: tH("rampa_webhooks_bc") }]}
        title={tH("rampa_webhooks_title")}
        subtitle={tH("rampa_webhooks_subtitle")}
      />

      {/* Cross-check strip */}
      <section className="prosper-card p-4 flex items-center gap-4 flex-wrap"
               data-testid="ramp-webhook-crosscheck">
        <GitCompareArrows size={16} className="text-primary"/>
        <div className="flex-1 min-w-0">
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
            Cross-check con Andes
          </div>
          <div className="text-sm text-fg font-display font-semibold">
            {deliv.data
              ? <>Andes entregó <span className="font-mono">{deliv.data.delivered_count}</span> · recibimos <span className="font-mono">{deliv.data.received_count}</span>
                  {deliv.data.delivered_count > deliv.data.received_count && (
                    <span className="ml-2 text-warning">⚠ entregas perdidas</span>
                  )}</>
              : "—"}
          </div>
          {deliv.data?.note && (
            <div className="text-[10px] text-fg-subtle">{deliv.data.note}</div>
          )}
        </div>
        <button onClick={() => { deliv.mutate(); list.mutate(); }}
                data-testid="ramp-webhook-refresh"
                className="prosper-btn-ghost h-8 text-[11px] gap-1.5">
          <RefreshCw size={11}/> Refrescar
        </button>
      </section>

      {/* Filters */}
      <section className="prosper-card p-4 flex flex-wrap items-end gap-3"
               data-testid="ramp-webhook-filters">
        <div className="flex-1 min-w-[220px]">
          <span className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
            Event type
          </span>
          <div className="relative mt-1">
            <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-subtle"/>
            <input
              value={type} onChange={e => setType(e.target.value)}
              placeholder="ej. fiat.deposit.success"
              data-testid="ramp-webhook-search"
              className="w-full pl-7 pr-3 h-9 rounded border border-border bg-bg text-fg text-sm font-mono focus:outline-none focus:border-primary"/>
          </div>
        </div>
        <FSel label="Procesado" value={processed} onChange={v => setP(v as any)}
               testid="ramp-webhook-filter-processed"
               opts={[["", "todos"], ["true", "procesados"], ["false", "fallidos"]]}/>
        <FSel label="Firma" value={sigValid} onChange={v => setSig(v as any)}
               testid="ramp-webhook-filter-sig"
               opts={[["", "todas"], ["true", "válidas"], ["false", "inválidas"]]}/>
      </section>

      <section className="prosper-card overflow-x-auto"
               data-testid="ramp-webhook-table">
        <table className="w-full text-xs">
          <thead className="bg-surface border-b border-border">
            <tr className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
              <th className="text-left  py-2 px-3">Recibido</th>
              <th className="text-left  py-2 px-3">Event type</th>
              <th className="text-left  py-2 px-3">Firma</th>
              <th className="text-left  py-2 px-3">Procesado</th>
              <th className="text-left  py-2 px-3">delivery_id</th>
            </tr>
          </thead>
          <tbody>
            {list.isLoading && (
              <tr><td colSpan={5} className="py-4 text-center italic text-fg-subtle">
                Cargando…</td></tr>
            )}
            {!list.isLoading && (list.data?.items.length ?? 0) === 0 && (
              <tr><td colSpan={5} className="py-6 text-center text-fg-subtle">
                Sin eventos</td></tr>
            )}
            {(list.data?.items || []).map(w => <WhRow key={w.delivery_id} w={w}/>)}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function WhRow({ w }: { w: WebhookEvent }) {
  return (
    <tr className="border-b border-border/40 hover:bg-surface/50"
        data-testid={`ramp-webhook-row-${w.delivery_id}`}>
      <td className="py-2 px-3 font-mono text-[10px] text-fg-muted">
        {new Date(w.received_at).toLocaleString()}
        {w.processed_at && (
          <div className="text-fg-subtle">→ {new Date(w.processed_at).toLocaleTimeString()}</div>
        )}
      </td>
      <td className="py-2 px-3 font-mono text-fg">{w.event_type}</td>
      <td className="py-2 px-3">
        {w.signature_valid
          ? <span className="inline-flex items-center gap-1 text-success text-[10px] font-mono"><ShieldCheck size={11}/> valid</span>
          : <span className="inline-flex items-center gap-1 text-danger text-[10px] font-mono"><ShieldOff size={11}/> invalid</span>}
      </td>
      <td className="py-2 px-3">
        <Badge tone={w.processed ? "success" : "danger"}>
          {w.processed ? "OK" : "FAIL"}
        </Badge>
        {w.error && (
          <div className="text-[10px] text-danger mt-0.5 max-w-[260px] truncate"
               title={w.error}>
            {w.error}
          </div>
        )}
      </td>
      <td className="py-2 px-3 font-mono text-[10px] text-fg-subtle">
        {w.delivery_id}
      </td>
    </tr>
  );
}

function FSel({ label, value, onChange, opts, testid }: {
  label: string; value: string; onChange: (v: string) => void;
  opts: [string, string][]; testid?: string;
}) {
  return (
    <label className="block">
      <span className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
        {label}
      </span>
      <select value={value} onChange={e => onChange(e.target.value)}
              data-testid={testid}
              className="mt-1 px-2.5 h-9 rounded border border-border bg-bg text-fg text-sm font-mono focus:outline-none focus:border-primary">
        {opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
}
