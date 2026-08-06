"use client";
import { useState } from "react";
import { PageHeader, Badge } from "@prosper/ui";
import {
  Plug, ShieldCheck, ScrollText, Mail, Coins, ArrowDownUp,
  Bell, CreditCard, Save, Zap, ExternalLink, Plus, Trash2, Check, X,
} from "lucide-react";
import { toast } from "sonner";
import {
  useIntegrations, patchIntegration, testIntegration,
  type Integration, type DocLink, type IntegrationField,
} from "@/lib/admin-settings";
import { cn, fmtDate } from "@/lib/utils";

const CATEGORY_ICON: Record<string, React.ComponentType<{ size?: number; className?: string }>> = {
  kyc_kyb:       ShieldCheck,
  screening:     ScrollText,
  email:         Mail,
  tokenization:  Coins,
  onramp:        ArrowDownUp,
  notifications: Bell,
  payments:      CreditCard,
};

const STATUS_TONE: Record<Integration["status"], "success" | "warning" | "danger"> = {
  active:  "success",
  partial: "warning",
  missing: "danger",
};

const STATUS_LABEL: Record<Integration["status"], string> = {
  active: "activa",
  partial: "parcial",
  missing: "falta config",
};

export default function IntegrationsPage() {
  const swr = useIntegrations();

  return (
    <div data-testid="admin-integrations-page">
      <PageHeader
        breadcrumbs={[{ label: "Admin", href: "/admin" },
                      { label: "Configuración", href: "/admin/settings" },
                      { label: "Integraciones" }]}
        kicker="Super admin · settings"
        title="Integraciones"
        subtitle="Conectar y administrar proveedores de terceros. Las env vars tienen precedencia sobre los valores guardados en DB."
      />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {(swr.data?.items ?? []).map((i) => (
          <IntegrationCard key={i.provider} integration={i}
            onChanged={() => swr.mutate()} />
        ))}
        {swr.isLoading && Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="prosper-card p-5 animate-pulse h-72" />
        ))}
      </div>

      <p className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mt-8">
        <span className="text-fg">/api/v1/admin/settings/integrations</span> ·
        cada cambio queda registrado en audit_log (sin loguear el valor de la key).
      </p>
    </div>
  );
}

function IntegrationCard({ integration: i, onChanged }:
  { integration: Integration; onChanged: () => void }) {
  const Icon = CATEGORY_ICON[i.category] || Plug;
  const [busy, setBusy]   = useState(false);
  const [testing, setTesting] = useState(false);
  const [fieldValues, setFieldValues] = useState<Record<string, string>>(
    Object.fromEntries(i.fields.map((f) => [f.key, f.value ?? ""])));
  const [mode, setMode]   = useState(i.mode);
  const [notes, setNotes] = useState(i.notes || "");
  const [docs, setDocs]   = useState<DocLink[]>(i.docs || []);

  const dirty = JSON.stringify(fieldValues) !== JSON.stringify(
        Object.fromEntries(i.fields.map((f) => [f.key, f.value ?? ""])))
    || mode !== i.mode
    || notes !== (i.notes || "")
    || JSON.stringify(docs) !== JSON.stringify(i.docs || []);

  const onSave = async () => {
    setBusy(true);
    try {
      // Only send fields that the user touched (different from current display)
      // — masked values (••••xxxx) are silently dropped by the backend.
      const fields: Record<string, unknown> = {};
      i.fields.forEach((f) => {
        const cur = fieldValues[f.key] ?? "";
        const prev = f.value ?? "";
        if (cur !== prev) fields[f.key] = cur;
      });
      await patchIntegration(i.provider, { fields,
        mode: i.supports_mode ? mode : undefined, notes, docs });
      toast.success(`${i.name} guardado`);
      onChanged();
    } catch (e: any) {
      toast.error(e?.message || "Save failed");
    } finally { setBusy(false); }
  };

  const onTest = async () => {
    setTesting(true);
    try { const res = await testIntegration(i.provider);
          if (res.ok) toast.success(res.message);
          else        toast.error(res.message);
          onChanged(); }
    catch (e: any) { toast.error(e?.message || "Test failed"); }
    finally { setTesting(false); }
  };

  return (
    <div className="prosper-card p-5"
         data-testid={`integration-card-${i.provider}`}>
      <div className="flex items-start gap-3 mb-3">
        <div className="w-9 h-9 rounded-lg bg-primary/10 text-primary
                        flex items-center justify-center shrink-0">
          <Icon size={16} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="font-display font-bold text-sm text-fg">{i.name}</h3>
            <Badge tone={STATUS_TONE[i.status]} size="sm"
                   data-testid={`integration-status-${i.provider}`}>
              {STATUS_LABEL[i.status]}
            </Badge>
            {i.supports_mode && (
              <button onClick={() => setMode(mode === "live" ? "sandbox" : "live")}
                data-testid={`integration-mode-${i.provider}`}
                className={cn(
                  "text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded border transition-colors",
                  mode === "live"
                    ? "border-danger/40 bg-danger/10 text-danger"
                    : "border-warning/40 bg-warning/10 text-warning",
                )}>
                {mode}
              </button>
            )}
          </div>
          <p className="text-[11px] text-fg-muted mt-1 leading-relaxed">{i.description}</p>
        </div>
        <div className="text-right shrink-0">
          <div className="text-[10px] font-mono text-fg-subtle">
            {i.required_filled}/{i.required_total} req
          </div>
          {i.last_test && (
            <div className={cn("text-[10px] font-mono mt-0.5",
                                i.last_test.ok ? "text-success" : "text-danger")}>
              {i.last_test.ok ? "✓" : "✗"} {fmtDate(i.last_test.tested_at || "")}
            </div>
          )}
        </div>
      </div>

      {/* Fields */}
      <div className="space-y-2.5 mb-4">
        {i.fields.map((f) => (
          <FieldRow key={f.key} field={f}
            value={fieldValues[f.key] ?? ""}
            onChange={(v) => setFieldValues({ ...fieldValues, [f.key]: v })}
            providerKey={i.provider}/>
        ))}
      </div>

      {/* Docs editor */}
      <DocsEditor provider={i.provider} docs={docs} setDocs={setDocs} />

      {/* Notes */}
      <details className="mt-3">
        <summary className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle cursor-pointer hover:text-fg">
          Notas internas {notes && <span className="text-fg ml-1">·</span>}
        </summary>
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)}
          placeholder={`Notas internas sobre ${i.name}…`}
          rows={3}
          data-testid={`integration-notes-${i.provider}`}
          className="mt-2 w-full px-3 py-2 rounded border border-border bg-surface text-xs
                     focus:outline-none focus:border-primary" />
      </details>

      <div className="flex items-center justify-between mt-4 pt-4 border-t border-border">
        <div className="text-[10px] font-mono text-fg-subtle">
          {i.updated_at && <>actualizado {fmtDate(i.updated_at)} por {i.updated_by}</>}
          {!i.updated_at && "sin cambios persistidos"}
        </div>
        <div className="flex items-center gap-2">
          {i.supports_test && (
            <button onClick={onTest} disabled={testing}
              data-testid={`integration-test-${i.provider}`}
              className="prosper-btn-ghost h-9 text-xs gap-1.5 disabled:opacity-50">
              <Zap size={13} /> {testing ? "Probando…" : "Test"}
            </button>
          )}
          <button onClick={onSave} disabled={busy || !dirty}
            data-testid={`integration-save-${i.provider}`}
            className="prosper-btn-primary h-9 text-xs gap-1.5 disabled:opacity-50">
            <Save size={13} /> {busy ? "Guardando…" : dirty ? "Guardar" : "Guardado"}
          </button>
        </div>
      </div>
    </div>
  );
}

function FieldRow({ field: f, value, onChange, providerKey }:
  { field: IntegrationField; value: string;
    onChange: (v: string) => void; providerKey: string }) {
  return (
    <div data-testid={`integration-field-${providerKey}-${f.key}`}>
      <div className="flex items-center justify-between mb-1">
        <label className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
          {f.label}
          {f.required && <span className="text-danger ml-1">*</span>}
        </label>
        <div className="flex items-center gap-1.5">
          {f.source === "env" && (
            <span data-testid={`field-source-env-${f.key}`}
              className="text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded
                         bg-success/10 text-success border border-success/30">
              env
            </span>
          )}
          {f.source === "db" && (
            <span className="text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded
                             bg-primary/10 text-primary border border-primary/30">
              db
            </span>
          )}
          {f.env_var && (
            <code className="text-[9px] font-mono text-fg-subtle">{f.env_var}</code>
          )}
        </div>
      </div>
      <input type={f.secret ? "password" : "text"}
        value={value} onChange={(e) => onChange(e.target.value)}
        placeholder={f.placeholder || (f.secret ? "(empty)" : "")}
        disabled={f.source === "env"}
        className={cn(
          "w-full px-3 py-2 rounded border bg-surface font-mono text-xs",
          "focus:outline-none focus:border-primary",
          f.source === "env" ? "border-success/30 text-fg-subtle cursor-not-allowed"
                              : "border-border",
        )}/>
      {f.source === "env" && (
        <p className="text-[10px] text-fg-subtle font-mono mt-1">
          Valor leído de <code>{f.env_var}</code>. Para editarlo en DB, primero quitá la env var.
        </p>
      )}
      {f.help && (
        <p className="text-[10px] text-fg-subtle mt-1">{f.help}</p>
      )}
    </div>
  );
}

function DocsEditor({ provider, docs, setDocs }:
  { provider: string; docs: DocLink[]; setDocs: (d: DocLink[]) => void }) {
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState<DocLink>({ title: "", url: "" });
  const onAdd = () => {
    if (!draft.title.trim() || !draft.url.trim()) return;
    setDocs([...docs, draft]); setDraft({ title: "", url: "" }); setAdding(false);
  };
  return (
    <div className="border-t border-border pt-3 mt-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
          API docs · referencias
        </span>
        <button onClick={() => setAdding(true)}
          data-testid={`integration-doc-add-${provider}`}
          className="prosper-btn-ghost h-7 px-2 text-[10px] font-mono uppercase tracking-wider gap-1">
          <Plus size={10}/> Add doc
        </button>
      </div>
      <div className="space-y-1.5">
        {docs.length === 0 && !adding && (
          <p className="text-[11px] text-fg-subtle italic">
            Sin docs cargadas. Cuando recibas el material del proveedor, pegá el link acá.
          </p>
        )}
        {docs.map((d, idx) => (
          <div key={idx} className="flex items-center gap-2 px-2 py-1.5 rounded
                                     bg-surface-hover/50 text-[11px]"
               data-testid={`integration-doc-${provider}-${idx}`}>
            <ExternalLink size={11} className="text-fg-subtle shrink-0" />
            <a href={d.url} target="_blank" rel="noreferrer"
               className="font-medium text-fg hover:text-primary truncate">{d.title}</a>
            <span className="text-fg-subtle font-mono truncate flex-1">{d.url}</span>
            <button onClick={() => setDocs(docs.filter((_, i) => i !== idx))}
              data-testid={`integration-doc-remove-${provider}-${idx}`}
              className="text-fg-subtle hover:text-danger">
              <Trash2 size={11}/>
            </button>
          </div>
        ))}
        {adding && (
          <div className="space-y-1.5 p-2 border border-primary/40 rounded bg-primary/5"
               data-testid={`integration-doc-form-${provider}`}>
            <input value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })}
              placeholder="Title (e.g. 'AlfredPay API v2 reference')"
              className="w-full px-2 py-1.5 rounded border border-border bg-surface text-[11px]"/>
            <input value={draft.url} onChange={(e) => setDraft({ ...draft, url: e.target.value })}
              placeholder="https://..."
              className="w-full px-2 py-1.5 rounded border border-border bg-surface font-mono text-[11px]"/>
            <div className="flex justify-end gap-1.5">
              <button onClick={() => setAdding(false)}
                className="text-[10px] px-2 py-1 rounded hover:bg-surface-hover">cancel</button>
              <button onClick={onAdd}
                data-testid={`integration-doc-save-${provider}`}
                className="text-[10px] px-2 py-1 rounded bg-primary text-white">add</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
