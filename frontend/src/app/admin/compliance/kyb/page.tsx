"use client";
import { useState } from "react";
import { useTranslations } from "next-intl";
import { PageHeader, Badge, DataTable, type Column } from "@prosper/ui";
import { Check, X, HelpCircle, ZoomIn, Shield } from "lucide-react";
import { toast } from "sonner";
import { useKybQueue, useKybCase, patchKybChecklist, decideKyb,
         type KybCase } from "@/lib/admin-compliance";
import { cn, fmtDate, fmtMoney } from "@/lib/utils";

const SLA_TONE: Record<string, string> = {
  green: "text-success border-success/40 bg-success/10",
  amber: "text-warning border-warning/40 bg-warning/10",
  red:   "text-danger  border-danger/40  bg-danger/10",
};

import { KybTray } from "./tray";
export default function KybPage() {
  // F6: con el módulo nuevo encendido, la bandeja nueva reemplaza a la
  // legacy en esta misma ruta (el banner legacy de la Fase 0 se va con
  // ella). Con el flag apagado, todo sigue exactamente como hoy.
  if (process.env.NEXT_PUBLIC_KYB_MODULE_ENABLED === "true")
    return <KybNewTrayPage />;
  return <KybLegacyPage />;
}

function KybNewTrayPage() {
  return (
    <div className="p-6" data-testid="kyb-new-tray-page">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-semibold text-fg">KYB — Bandeja de casos</h1>
        <div className="flex gap-3 text-xs" data-testid="kyb-module-links">
          <a href="/admin/compliance/kyb/settings" className="text-primary hover:underline"
             data-testid="kyb-settings-link">Modos de verificación</a>
          <a href="/admin/compliance/kyb/templates" className="text-primary hover:underline"
             data-testid="kyb-templates-link">Plantillas de checklist</a>
        </div>
      </div>
      <KybTray />
    </div>
  );
}

function KybLegacyPage() {
  const tH = useTranslations("admin.headers");
  const tA = useTranslations("admin");
  const queue = useKybQueue();
  const [activeId, setActiveId] = useState<string | null>(null);

  const cols: Column<KybCase>[] = [
    { key: "legal_name", header: "Razón social", sortable: true,
      render: (r) => (<div>
        <div className="text-fg">{r.legal_name}</div>
        <div className="text-[10px] text-fg-subtle font-mono">{r.commercial_name}</div>
      </div>) },
    { key: "country", header: "País", width: "60px",
      render: (r) => <span className="font-mono text-[11px]">{r.country}</span> },
    { key: "type", header: "Tipo", width: "120px",
      render: (r) => <Badge tone="auto" size="sm">{r.type}</Badge> },
    { key: "applied_at", header: "Aplicado", width: "130px",
      render: (r) => <span className="font-mono text-[11px]">{fmtDate(r.applied_at)}</span> },
    { key: "provider_score", header: "Score", numeric: true, sortable: true, width: "70px", align: "right",
      render: (r) => <span className="font-mono tabular">{r.provider_score}</span> },
    { key: "sla_hours_left", header: "SLA", width: "100px",
      render: (r) => <span className={cn("font-mono text-[10px] px-2 py-0.5 rounded-full border",
        SLA_TONE[r.sla_color || "green"])}>{r.sla_hours_left.toFixed(1)}h</span> },
    { key: "status", header: "Status", width: "100px",
      render: (r) => <Badge size="sm"
        tone={r.status === "approved" ? "success" : r.status === "rejected" ? "danger" : "warning"}>
        {r.status}</Badge> },
    { key: "checklist_progress", header: "Checklist", width: "140px",
      render: (r) => {
        const p = r.checklist_progress;
        return (
          <div className="flex items-center gap-2">
            <div className="w-16 h-1 rounded bg-surface-hover overflow-hidden">
              <div className="h-full bg-primary"
                   style={{width: `${(p.checked/p.total)*100}%`}}/>
            </div>
            <span className="font-mono text-[10px] tabular">
              {p.checked}/{p.total}{p.ready_to_approve ? " ✓" : ""}
            </span>
          </div>
        );
      } },
  ];

  return (
    <div data-testid="compl-kyb-page">
      {/* PRELIMINARY MODULE BANNER — Fase 0 (Aug 2026)
          This bandeja does NOT run any external verification. It is a
          register of administrative decisions, NOT a compliance
          verification. Must remain visible while KYB_MODULE_ENABLED is
          off — do not make it dismissible. */}
      <div role="alert" data-testid="kyb-preliminary-banner"
           className="mb-4 rounded-md border-2 border-warning bg-warning/10 p-4">
        <p className="font-display font-bold text-sm text-warning-fg mb-1">
          Módulo preliminar
        </p>
        <p className="text-xs text-fg leading-relaxed">
          Esta bandeja no ejecuta verificación externa: no consulta listas
          de sanciones, no valida documentación societaria ni verifica
          identidad. Las decisiones tomadas acá son registros
          administrativos, no verificaciones de cumplimiento.
        </p>
      </div>

      <PageHeader
        breadcrumbs={[{ label: tA("breadcrumb_admin"), href: "/admin" },
                      { label: tH("comp_label"), href: "/admin/compliance" },
                      { label: tH("comp_kyb_bc") }]}
        kicker={tH("comp_kyb_kicker")}
        title={tH("comp_kyb_title")}
        subtitle={tH("comp_kyb_subtitle")} />

      <DataTable<KybCase>
        data={queue.data?.items ?? []} columns={cols}
        rowKey={(r) => r.case_id}
        onRowClick={(r) => setActiveId(r.case_id)}
        empty={queue.isLoading ? "Loading…" : "No KYB cases"} />

      {activeId && (
        <KybDrawer caseId={activeId}
          onClose={() => setActiveId(null)}
          onChanged={() => queue.mutate()}
          onDecided={() => { queue.mutate(); setActiveId(null); }} />
      )}
    </div>
  );
}

function KybDrawer({ caseId, onClose, onChanged, onDecided }:
  { caseId: string; onClose: () => void; onChanged: () => void; onDecided: () => void }) {
  const swr = useKybCase(caseId);
  const c = swr.data;
  const [action, setAction] = useState<"approve" | "reject" | "request_info" | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [zoom, setZoom] = useState<string | null>(null);

  const toggleItem = async (key: string, checked: boolean) => {
    try { await patchKybChecklist(caseId, key, checked); await swr.mutate(); onChanged(); }
    catch (e: any) { toast.error(e?.message || "Patch failed"); }
  };
  const submit = async () => {
    if (!action || reason.length < 20) { toast.error("Motivo mínimo 20 chars"); return; }
    setBusy(true);
    try { await decideKyb(caseId, { action, reason });
          toast.success(`KYB ${action} ok`); onDecided(); }
    catch (e: any) { toast.error(e?.message || "Decision failed"); }
    finally { setBusy(false); }
  };

  const ready = c?.checklist_progress?.ready_to_approve;

  return (
    <div className="fixed inset-0 z-40 flex" data-testid="kyb-drawer">
      <div className="flex-1 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="w-full max-w-[920px] bg-bg border-l border-border h-full overflow-y-auto p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">KYB case</div>
            <h2 className="font-display font-bold text-xl">{c?.legal_name || "…"}</h2>
            {c && <div className="text-[11px] font-mono text-fg-subtle">
              {c.country} · {c.type} · {c.tax_id}</div>}
          </div>
          <button onClick={onClose} className="prosper-btn-ghost h-8 px-3 text-xs"
                  data-testid="kyb-drawer-close">Close</button>
        </div>

        {!c ? <div className="text-fg-subtle">Loading…</div> : (
          <div className="space-y-6">
            <section>
              <h3 className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-2">
                Información societaria</h3>
              <div className="grid grid-cols-4 gap-2.5">
                <Stat label="País" value={c.country} />
                <Stat label="Tipo" value={c.type} />
                <Stat label="Tax ID" value={c.tax_id} />
                <Stat label="Incorporación" value={c.incorporation_date} />
              </div>
            </section>

            <section>
              <h3 className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-2">
                Documentos</h3>
              <div className="grid grid-cols-3 gap-3">
                {c.documents.map((d, i) => (
                  <button key={i} onClick={() => setZoom(d.url)}
                    data-testid={`kyb-doc-${i}`}
                    className="relative group rounded border border-border overflow-hidden">
                    <img src={d.url} alt={d.label}
                         className="w-full h-28 object-cover bg-surface" />
                    <div className="absolute inset-0 bg-fg/40 opacity-0 group-hover:opacity-100
                                    transition-opacity flex items-center justify-center">
                      <ZoomIn size={18} className="text-white" />
                    </div>
                    <div className="absolute bottom-0 inset-x-0 bg-fg/80 text-bg px-2 py-1
                                    text-[9px] font-mono uppercase tracking-wider truncate">
                      {d.label}
                    </div>
                  </button>
                ))}
              </div>
            </section>

            <section>
              <h3 className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-2">
                UBOs · Beneficial owners</h3>
              <table className="w-full text-xs">
                <thead className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
                  <tr className="border-b border-border">
                    <th className="text-left py-2">Nombre</th>
                    <th className="text-right py-2">%</th>
                    <th className="text-left py-2">Nacionalidad</th>
                    <th className="text-left py-2">PEP</th>
                    <th className="text-left py-2">Verificado</th>
                  </tr>
                </thead>
                <tbody>
                  {c.ubos.map((u, i) => (
                    <tr key={i} className="border-b border-border" data-testid={`kyb-ubo-${i}`}>
                      <td className="py-2">{u.name}</td>
                      <td className="py-2 text-right font-mono tabular">{u.ownership_pct}%</td>
                      <td className="py-2 font-mono">{u.nationality}</td>
                      <td className="py-2">
                        {u.is_pep ? <Badge tone="danger" size="sm">PEP</Badge>
                                  : <span className="text-fg-subtle">—</span>}
                      </td>
                      <td className="py-2">
                        {u.verified ? <Check size={14} className="text-success"/>
                                    : <span className="text-fg-subtle">pending</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>

            <section>
              <h3 className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-2
                              flex items-center gap-2">
                <Shield size={12}/> Checklist obligatorio
                <span className="text-fg-subtle">·</span>
                <span className={cn(ready ? "text-success" : "text-warning")}
                      data-testid="kyb-checklist-progress">
                  {c.checklist_progress.checked}/{c.checklist_progress.total}
                </span>
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-1.5">
                {c.checklist.map((it) => (
                  <label key={it.key}
                    data-testid={`kyb-cl-${it.key}`}
                    className="flex items-center gap-2 px-3 py-2 rounded border border-border
                               hover:bg-surface-hover cursor-pointer text-xs">
                    <input type="checkbox" checked={it.checked}
                      onChange={(e) => toggleItem(it.key, e.target.checked)}
                      className="rounded border-border" />
                    <span className={cn(it.checked && "text-fg-subtle line-through")}>{it.label}</span>
                  </label>
                ))}
              </div>
            </section>

            <section>
              <h3 className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-2">
                Decisión</h3>
              {/* PRELIMINARY MODULE BANNER — Fase 0 (Aug 2026) — see top of page */}
              <div role="alert" data-testid="kyb-decision-banner"
                   className="mb-3 rounded-md border-2 border-warning bg-warning/10 p-3">
                <p className="font-display font-bold text-[11px] text-warning-fg mb-1">
                  Módulo preliminar
                </p>
                <p className="text-[11px] text-fg leading-relaxed">
                  Esta decisión NO ejecuta verificación externa: no consulta
                  listas de sanciones, no valida documentación societaria ni
                  verifica identidad. Es un registro administrativo, no una
                  verificación de cumplimiento.
                </p>
              </div>
              <div className="grid grid-cols-3 gap-2 mb-3">
                {(["approve", "reject", "request_info"] as const).map((a) => {
                  const disabled = a === "approve" && !ready;
                  return (
                    <button key={a} onClick={() => setAction(a)} disabled={disabled}
                      data-testid={`kyb-action-${a}`}
                      className={cn("h-12 rounded-md font-mono uppercase text-[11px] tracking-wider border-2 transition-colors disabled:opacity-40 disabled:cursor-not-allowed",
                        action === a
                          ? a === "approve" ? "bg-success text-white border-success"
                            : a === "reject" ? "bg-danger text-white border-danger"
                            : "bg-warning text-white border-warning"
                          : "border-border text-fg-muted hover:text-fg")}>
                      {a === "approve" ? `Aprobar${!ready ? " (bloqueado)" : ""}`
                        : a === "reject" ? "Rechazar" : "Solicitar info"}
                    </button>
                  );
                })}
              </div>
              <textarea value={reason} onChange={(e) => setReason(e.target.value)}
                placeholder="Motivo (mínimo 20 caracteres)"
                rows={3}
                data-testid="kyb-reason"
                className="w-full px-3 py-2 rounded border border-border bg-surface
                           font-mono text-xs focus:outline-none focus:border-primary" />
              <div className="flex items-center justify-between mt-3">
                <span className="text-[10px] font-mono text-fg-subtle">{reason.length}/20+ chars</span>
                <button onClick={submit} disabled={!action || reason.length < 20 || busy}
                  data-testid="kyb-submit-decision"
                  className="prosper-btn-primary h-9 text-xs disabled:opacity-50">
                  {busy ? "Enviando…" : "Ejecutar decisión"}
                </button>
              </div>
            </section>
          </div>
        )}

        {zoom && (
          <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-8"
               onClick={() => setZoom(null)} data-testid="kyb-zoom">
            <img src={zoom} alt="" className="max-w-full max-h-full rounded shadow-2xl" />
          </div>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="prosper-card p-3">
      <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">{label}</div>
      <div className="text-fg font-mono text-sm mt-0.5">{value}</div>
    </div>
  );
}
