"use client";
/* Fase 6 — Detalle completo del caso KYB (absorbe la vista provisional 5a). */
import { notFound, useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { kybEnabled } from "@/app/kyb/_components/KybShell";
import { api } from "@/lib/api";
import { ManualChecksTab } from "../manual-tab";

const BASE = "/v1/admin/compliance/kyb";
const TABS = ["Expediente", "Beneficiarios", "Documentos", "Verificaciones",
  "Verificación manual", "Screening", "Registro", "Riesgo", "Auditoría"];
const SECTION_LABELS: Record<string, string> = {
  tax_identification: "Identificación fiscal",
  legal_representative: "Representante legal",
  company_data: "Datos de la empresa", documentation: "Documentación" };

export default function KybCaseDetailPage() {
  if (!kybEnabled()) notFound();
  const { caseId } = useParams<{ caseId: string }>();
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState("");
  const [tab, setTab] = useState("Expediente");
  const load = useCallback(() => api<any>(`${BASE}/cases/${caseId}`)
    .then((r) => { setD(r); setErr(""); })
    .catch((e) => setErr(e?.message || "Error")), [caseId]);
  useEffect(() => { load(); }, [load]);
  if (err) return <p className="p-6 text-sm text-danger" data-testid="kyb-detail-error">{err}</p>;
  if (!d) return <p className="p-6 text-sm text-fg-muted">Cargando…</p>;
  const c = d.case;

  async function act(path: string, body?: any, ok = "Listo") {
    try {
      const r = await api<any>(`${BASE}/cases/${caseId}/${path}`,
        { method: "POST", body: JSON.stringify(body || {}) });
      toast.success(r.pending_second_approval
        ? "Primera firma registrada — falta la segunda" : ok);
      await load();
    } catch (e: any) { toast.error(e?.message || "Error"); }
  }

  return (
    <div className="p-6 pb-24" data-testid="kyb-case-detail">
      {/* Encabezado */}
      <div className="mb-2">
        <h1 className="text-xl font-semibold text-fg">{c.company_name_declared || c.case_id}</h1>
        <p className="text-xs text-fg-muted font-mono" data-testid="kyb-detail-header">
          {c.case_id} · estado: {c.status}{c.suspended ? " · OPERATORIA SUSPENDIDA" : ""} ·
          riesgo: {c.risk?.level || "sin evaluar"} · analista: {c.assigned_to || "sin asignar"} ·
          {" "}{Object.entries(c.verification_modes || {}).map(([k, v]: any) => {
            const st = c.verification_states?.[k]?.state;
            return `${k}=${st === "not_configured" ? "not_configured" : v}`; }).join(" ")}
          {" "}· SLA: {d.sla || "—"}
        </p>
        <div className="mt-1 flex gap-2">
          <input className="rounded border border-border bg-bg px-2 py-1 text-xs w-56"
                 placeholder="Asignar a (user_id)…" data-testid="kyb-assign-input"
                 onKeyDown={(e: any) => e.key === "Enter" &&
                   act("assign", { assignee_user_id: e.target.value || null }, "Asignado")} />
        </div>
      </div>
      {c.legacy_origin && (
        <div className="mb-3 rounded-md border border-warning/50 bg-warning/10 p-3 text-xs text-fg"
             data-testid="kyb-legacy-banner">
          <strong>Expediente migrado del sistema anterior.</strong> La documentación
          no fue capturada por la plataforma: hay que solicitarla al cliente antes
          de resolver.
          {!c.applicant_email && (
            <span data-testid="kyb-no-contact-warning"> Este expediente <strong>no tiene
            contacto registrado</strong> — capturalo antes de solicitar información:{" "}
              <input className="rounded border border-border bg-bg px-2 py-0.5 text-xs w-52"
                     placeholder="email de contacto" data-testid="kyb-contact-email-input"
                     onKeyDown={(e: any) => e.key === "Enter" &&
                       act("contact-email", { email: e.target.value }, "Contacto registrado")} />
            </span>)}
        </div>)}
      {c.pending_second_approval && (
        <div className="mb-3 rounded-md border border-primary/50 bg-primary/10 p-3 text-xs text-fg"
             data-testid="kyb-second-signature-banner">
          Primera firma de <span className="font-mono">{c.pending_second_approval.first_by}</span> registrada.
          Falta: {c.pending_second_approval.requires}.
        </div>)}

      <div className="flex gap-1 border-b border-border mb-4 overflow-x-auto">
        {TABS.map((t) => (
          <button key={t} data-testid={`kyb-tab-${t.toLowerCase().replace(/ /g, "-")}`}
                  className={`px-3 py-2 text-sm whitespace-nowrap border-b-2 -mb-px ${
                    tab === t ? "border-primary text-primary" : "border-transparent text-fg-muted hover:text-fg"}`}
                  onClick={() => setTab(t)}>{t}</button>))}
      </div>

      {tab === "Expediente" && <ExpTab d={d} act={act} />}
      {tab === "Beneficiarios" && <UboTab d={d} />}
      {tab === "Documentos" && <DocsTab caseId={caseId} d={d} />}
      {tab === "Verificaciones" && <VerifTab d={d} />}
      {tab === "Verificación manual" && <ManualChecksTab caseId={caseId} />}
      {tab === "Screening" && <ScreeningTab caseId={caseId} reload={load} />}
      {tab === "Registro" && <RegistryTab caseId={caseId} reload={load} />}
      {tab === "Riesgo" && <RiskTab d={d} act={act} />}
      {tab === "Auditoría" && <AuditTab caseId={caseId} />}

      {/* Barra inferior fija */}
      <div className="fixed bottom-0 left-0 right-0 border-t border-border bg-surface/95 backdrop-blur px-6 py-3 flex gap-3 justify-end z-40"
           data-testid="kyb-action-bar">
        <a className="rounded-lg border border-border px-4 py-2 text-sm text-fg hover:bg-bg"
           data-testid="kyb-export-button"
           href={`/api${BASE}/cases/${caseId}/export`}
           target="_blank" rel="noopener">Descargar legajo</a>
        <button className="rounded-lg border border-border px-4 py-2 text-sm text-fg hover:bg-bg"
                data-testid="kyb-rerun-button"
                onClick={() => act("rerun-verifications", {},
                  "Verificaciones re-ejecutadas")}>Re-ejecutar verificaciones</button>
        {/* F8-fix (post-diag 6 puntos): las acciones de resolución sólo
            existen cuando el caso está bajo revisión. La state machine
            no admite aprobar/rechazar/observar desde submitted o
            screening — el botón desaparece del DOM, no queda en
            disabled cosmético. */}
        {c.status === "under_review" && (<>
          <ActionWithReason label="Solicitar información" testid="kyb-request-info-button"
                            needsReason={false} onGo={() => act("request-info", {}, "Información solicitada")} />
          <ActionWithReason label="Rechazar" testid="kyb-reject-button" danger
                            reasonCodes={d.reject_reason_codes}
                            onGoWith={(code: string, notes: string) => act("reject", { reason_code: code, notes }, "Caso rechazado")} />
          <button className="rounded-lg bg-primary text-white px-4 py-2 text-sm hover:opacity-90"
                  data-testid="kyb-approve-button"
                  onClick={() => act("approve", {}, "Caso aprobado")}>Aprobar</button>
        </>)}
        {(c.status === "submitted" || c.status === "screening") && (
          <p className="text-xs text-fg-muted italic px-2 py-2 self-center"
             data-testid="kyb-action-bar-not-under-review">
            El expediente aún no llegó a revisión — completá los
            checklists manuales para habilitar las acciones.</p>)}
        {c.status === "approved" && !c.suspended && (
          <ActionWithReason label="Suspender operatoria" testid="kyb-suspend-button" danger
                            onGoWith={(_: string, notes: string) => act("suspend", { reason: notes }, "Operatoria suspendida")} />)}
        {c.suspended && (
          <ActionWithReason label="Levantar suspensión" testid="kyb-unsuspend-button"
                            onGoWith={(_: string, notes: string) => act("unsuspend", { reason: notes }, "Suspensión levantada")} />)}
      </div>
    </div>
  );
}

function ActionWithReason({ label, testid, danger, reasonCodes, needsReason = true, onGo, onGoWith }: any) {
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState("");
  const [notes, setNotes] = useState("");
  if (!needsReason && onGo) return (
    <button className="rounded-lg border border-border px-4 py-2 text-sm text-fg hover:bg-bg"
            data-testid={testid} onClick={onGo}>{label}</button>);
  return (
    <>
      <button className={`rounded-lg border px-4 py-2 text-sm hover:bg-bg ${
                danger ? "border-danger/50 text-danger" : "border-border text-fg"}`}
              data-testid={testid} onClick={() => setOpen(true)}>{label}</button>
      {open && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
          <div className="bg-surface border border-border rounded-2xl p-5 max-w-md w-full">
            <h2 className="text-base font-semibold text-fg mb-3">{label}</h2>
            {reasonCodes && (
              <select className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm mb-2"
                      value={code} data-testid={`${testid}-code`}
                      onChange={(e) => setCode(e.target.value)}>
                <option value="">Motivo tipificado…</option>
                {reasonCodes.map((r: string) => <option key={r} value={r}>{r}</option>)}
              </select>)}
            <textarea className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm" rows={3}
                      placeholder="Motivo / notas (mín. 10 caracteres)" value={notes}
                      data-testid={`${testid}-notes`}
                      onChange={(e) => setNotes(e.target.value)} />
            <div className="flex gap-2 mt-3">
              <button className="flex-1 rounded-lg border border-border py-2 text-sm"
                      onClick={() => setOpen(false)}>Cancelar</button>
              <button className="flex-1 rounded-lg bg-primary text-white py-2 text-sm disabled:opacity-50"
                      disabled={notes.trim().length < 10 || (reasonCodes && !code)}
                      data-testid={`${testid}-confirm`}
                      onClick={() => { setOpen(false); onGoWith(code, notes); }}>Confirmar</button>
            </div>
          </div>
        </div>)}
    </>
  );
}

function ExpTab({ d, act }: any) {
  const sections = d.case.sections || {};
  const [obs, setObs] = useState<Record<string, string>>({});
  return (
    <div className="space-y-3" data-testid="kyb-exp-tab">
      {Object.keys(SECTION_LABELS).map((k) => {
        const s = sections[k] || {};
        return (
          <div key={k} className="bg-surface border border-border rounded-xl p-4"
               data-testid={`kyb-exp-section-${k}`}>
            <div className="flex items-center gap-3">
              <div className="flex-1">
                <p className="text-sm font-medium text-fg">{SECTION_LABELS[k]}</p>
                <p className="text-xs text-fg-muted font-mono">
                  cliente: {s.status || "pending"} · revisión: {s.review_status || "pendiente"}
                  {s.observed_by && ` · observada por ${s.observed_by}`}</p>
                {s.observation && <p className="text-xs text-warning mt-1">Observación: {s.observation}</p>}
              </div>
              <button className="rounded-lg border border-border px-3 py-1.5 text-xs hover:bg-bg"
                      data-testid={`kyb-approve-section-${k}`}
                      onClick={() => act(`sections/${k}/review`, { action: "approve" }, "Sección aprobada")}>
                Aprobar sección</button>
            </div>
            <div className="flex gap-2 mt-2">
              <input className="flex-1 rounded-lg border border-border bg-bg px-3 py-1.5 text-xs"
                     placeholder="Detalle que verá el cliente. Sea claro y específico."
                     value={obs[k] || ""} data-testid={`kyb-observe-input-${k}`}
                     onChange={(e) => setObs({ ...obs, [k]: e.target.value })} />
              <button className="rounded-lg border border-warning/50 text-warning px-3 py-1.5 text-xs hover:bg-warning/10 disabled:opacity-40"
                      disabled={(obs[k] || "").trim().length < 10}
                      data-testid={`kyb-observe-section-${k}`}
                      onClick={() => act(`sections/${k}/review`,
                        { action: "observe", observation: obs[k] }, "Sección observada")}>
                Observar sección</button>
            </div>
          </div>);
      })}
    </div>
  );
}

function UboTab({ d }: any) {
  const conf = d.case.ubo_confirmation;
  return (
    <div data-testid="kyb-ubo-tab">
      {conf?.acknowledged_incomplete && (
        <p className="mb-3 rounded-md border border-warning/50 bg-warning/10 p-2.5 text-xs text-fg"
           data-testid="kyb-ubo-incomplete-flag">
          ⚠ Cuadro societario incompleto: el cliente aceptó continuar con el{" "}
          <strong>{conf.ownership_percentage_at_acknowledgment}%</strong> declarado
          (actual: {conf.total_percentage}%).</p>)}
      <table className="w-full text-sm rounded-xl border border-border overflow-hidden">
        <thead className="bg-bg text-left text-xs text-fg-muted">
          <tr>{["Nombre", "%", "PEP", "Suj. obligado", "Screening", "Identidad"].map((h) =>
            <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-border bg-surface">
          {(d.ubos || []).map((u: any) => (
            <tr key={u.ubo_id} data-testid={`kyb-ubo-row-${u.ubo_id}`}>
              <td className="px-3 py-2">{u.first_name} {u.last_name}
                {u.control_type === "CONTROL_BODY" && <span className="ml-1 text-xs text-fg-muted">(órgano de control)</span>}
                {u.is_also_legal_representative && <span className="ml-1 text-xs text-primary">rep. legal</span>}</td>
              <td className="px-3 py-2">{u.ownership_percentage ?? "—"}</td>
              <td className="px-3 py-2">{u.is_pep ? "Sí" : "No"}</td>
              <td className="px-3 py-2">{u.is_obliged_subject ? "Sí" : "No"}</td>
              <td className="px-3 py-2 font-mono text-xs">{u.screening_status || "—"}</td>
              <td className="px-3 py-2 font-mono text-xs">{u.identity_status || "—"}</td>
            </tr>))}
        </tbody>
      </table>
    </div>
  );
}

function DocsTab({ caseId, d }: any) {
  const [viewing, setViewing] = useState<{ id: string; url: string } | null>(null);
  async function view(id: string) {
    try {
      const r = await api<any>(`${BASE}/cases/${caseId}/documents/${id}/url`);
      setViewing({ id, url: r.url });
    } catch (e: any) { toast.error(e?.message); }
  }
  return (
    <div data-testid="kyb-docs-tab">
      <div className="space-y-2">
        {(d.documents || []).map((doc: any) => (
          <div key={doc.document_id}
               className={`flex items-center gap-3 rounded-lg border border-border bg-surface px-3 py-2 text-sm ${doc.is_current ? "" : "opacity-50"}`}
               data-testid={`kyb-doc-row-${doc.document_id}`}>
            <div className="flex-1 min-w-0">
              <p className="text-fg truncate">{doc.filename}
                {doc.discarded && <span className="ml-1.5 text-xs text-danger">descartada</span>}</p>
              <p className="text-[11px] text-fg-muted font-mono">
                {doc.slot} · v{doc.version} · {doc.created_at?.slice(0, 10)} ·
                por {doc.uploaded_by} · origen: {doc.uploaded_via}
                {doc.description && ` · ${doc.description}`}</p>
            </div>
            <button className="text-primary text-xs hover:underline"
                    data-testid={`kyb-doc-view-${doc.document_id}`}
                    onClick={() => view(doc.document_id)}>Ver</button>
          </div>))}
      </div>
      {viewing && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-6"
             onClick={() => setViewing(null)} data-testid="kyb-doc-viewer">
          <iframe src={viewing.url} className="bg-white rounded-xl w-full max-w-3xl h-[80vh]"
                  title="Documento" />
        </div>)}
    </div>
  );
}

function VerifTab({ d }: any) {
  const states = d.case.verification_states || {};
  return (
    <div className="space-y-3" data-testid="kyb-verif-tab">
      <p className="text-xs text-fg-muted font-mono">
        {Object.entries(states).map(([k, v]: any) => `${k}: ${v?.state}`).join(" · ") || "sin estados"}
      </p>
      {(d.verifications || []).length === 0 && (
        <p className="text-sm text-fg-muted rounded-xl border-2 border-dashed border-border p-6 text-center"
           data-testid="kyb-verif-empty">Sin verificaciones registradas todavía —
          completá los checklists manuales para producirlas.</p>)}
      {(d.verifications || []).map((v: any) => (
        <div key={v.verification_id} className="bg-surface border border-border rounded-xl p-4"
             data-testid={`kyb-verif-${v.verification_id}`}>
          <p className="text-sm text-fg font-medium">
            {v.kind} — {v.subject_type} <span className="font-mono text-xs">{v.subject_id}</span></p>
          <p className="text-xs text-fg-muted font-mono">
            modo: {v.mode} · fuente: {v.source} · por: {v.performed_by || "—"} ·
            resultado: <span className={
              v.outcome === "hit" ? "text-danger" :
              v.outcome === "review" ? "text-warning" : "text-success"}>{v.outcome}</span>
            {v.normalized_result?.hit_count > 0 && ` · ${v.normalized_result.hit_count} hit(s)`}
          </p>
          {(v.normalized_result?.items || []).map((i: any) => (
            <p key={i.item_key} className="text-[11px] text-fg-muted ml-2">· {i.label}: {i.outcome}</p>))}
        </div>))}
      <p className="text-[11px] text-fg-muted">
        Estados de caída: <span className="text-warning">inconclusive</span> es
        reintentable; <span className="text-danger">fail</span> es rechazo del
        proveedor. <span className="font-mono">not_configured</span> equivale a
        manual sin credenciales y se muestra explícito.</p>
    </div>
  );
}

function RiskTab({ d, act }: any) {
  const r = d.case.risk || {};
  const [level, setLevel] = useState(r.level || "medium");
  const [just, setJust] = useState("");
  return (
    <div className="max-w-xl space-y-3" data-testid="kyb-risk-tab">
      <div className="bg-surface border border-border rounded-xl p-4">
        <p className="text-sm text-fg">Nivel: <strong data-testid="kyb-risk-level">{r.level || "sin evaluar"}</strong>
          {r.overridden && <span className="ml-2 text-xs text-warning">override por {r.overridden_by}</span>}</p>
        <p className="text-xs text-fg-muted font-mono">puntaje: {r.score ?? "—"} ·
          modelo: {r.model_version ? `v${r.model_version}` : "sin calcular"}</p>
        {(r.factors || []).map((f: any, i: number) => (
          <p key={i} className="text-[11px] text-fg-muted ml-2">· {f.name || f}: {f.score ?? ""}</p>))}
        {r.override_justification && (
          <p className="text-xs text-fg-muted mt-1">Justificación: {r.override_justification}</p>)}
      </div>
      <div className="flex gap-2">
        <select className="rounded-lg border border-border bg-bg px-2 py-2 text-sm"
                value={level} data-testid="kyb-risk-override-level"
                onChange={(e) => setLevel(e.target.value)}>
          {["low", "medium", "high"].map((l) => <option key={l} value={l}>{l}</option>)}
        </select>
        <input className="flex-1 rounded-lg border border-border bg-bg px-3 py-2 text-sm"
               placeholder="Justificación obligatoria (mín. 10 caracteres)"
               value={just} data-testid="kyb-risk-override-just"
               onChange={(e) => setJust(e.target.value)} />
        <button className="rounded-lg bg-primary text-white px-3 py-2 text-sm disabled:opacity-40"
                disabled={just.trim().length < 10} data-testid="kyb-risk-override-button"
                onClick={() => act("risk-override", { level, justification: just }, "Riesgo actualizado")}>
          Override</button>
      </div>
    </div>
  );
}

function AuditTab({ caseId }: { caseId: string }) {
  const [rows, setRows] = useState<any[]>([]);
  const [f, setF] = useState({ action: "", actor: "" });
  const load = useCallback(() => {
    const p = new URLSearchParams();
    if (f.action) p.set("action", f.action);
    if (f.actor) p.set("actor", f.actor);
    api<any>(`${BASE}/cases/${caseId}/audit?${p}`).then((r) => setRows(r.items))
      .catch((e) => toast.error(e?.message));
  }, [caseId, f]);
  useEffect(() => { load(); }, [load]);
  return (
    <div data-testid="kyb-audit-tab">
      <div className="flex gap-2 mb-3">
        <input className="rounded-lg border border-border bg-bg px-3 py-1.5 text-xs w-64"
               placeholder="Filtrar por tipo de evento (ej. kyb.ubo.created)"
               value={f.action} data-testid="kyb-audit-filter-action"
               onChange={(e) => setF({ ...f, action: e.target.value })} />
        <input className="rounded-lg border border-border bg-bg px-3 py-1.5 text-xs w-48"
               placeholder="Actor (user_id)" value={f.actor}
               data-testid="kyb-audit-filter-actor"
               onChange={(e) => setF({ ...f, actor: e.target.value })} />
      </div>
      <div className="space-y-1">
        {rows.map((r, i) => (
          <div key={i} className="rounded-lg border border-border bg-surface px-3 py-2 text-xs"
               data-testid={`kyb-audit-row-${i}`}>
            <span className="font-mono text-fg">{r.action}</span>
            <span className="text-fg-muted"> · {r.timestamp?.slice(0, 19)} ·
              actor: {r.actor_user_id || "system"}</span>
          </div>))}
        {rows.length === 0 && <p className="text-sm text-fg-muted">Sin eventos para el filtro.</p>}
      </div>
    </div>
  );
}


/* -------------------------------- Fase 7 -------------------------------- */
function ScreeningTab({ caseId, reload }: { caseId: string; reload: () => void }) {
  const [data, setData] = useState<any>(null);
  const [busy, setBusy] = useState("");
  const load = useCallback(() => api<any>(`${BASE}/cases/${caseId}/screening`)
    .then(setData).catch((e) => toast.error(e?.message)), [caseId]);
  useEffect(() => { load(); }, [load]);
  if (!data) return <p className="text-sm text-fg-muted">Cargando…</p>;

  async function resolve(hitId: string, decision: string, notes: string) {
    if (notes.trim().length < 20) {
      toast.error("La nota debe tener al menos 20 caracteres"); return; }
    setBusy(hitId);
    try {
      await api(`${BASE}/hits/${hitId}/resolve`,
        { method: "POST", body: JSON.stringify({ decision, notes }) });
      toast.success("Hit resuelto"); await load(); reload();
    } catch (e: any) { toast.error(e?.message); }
    finally { setBusy(""); }
  }
  async function toggleBlock(hitId: string, isBlocking: boolean, reason: string) {
    if (reason.trim().length < 10) {
      toast.error("Motivo requerido (mín. 10 caracteres)"); return; }
    const path = isBlocking ? "demote-blocking" : "promote-blocking";
    setBusy(hitId);
    try {
      await api(`${BASE}/hits/${hitId}/${path}`,
        { method: "POST", body: JSON.stringify({ reason }) });
      toast.success(isBlocking ? "Ya no bloquea" : "Marcado como bloqueante");
      await load(); reload();
    } catch (e: any) { toast.error(e?.message); }
    finally { setBusy(""); }
  }

  return (
    <div className="space-y-4" data-testid="kyb-screening-tab">
      <p className="text-xs text-fg-muted">
        Hits bloqueantes sin resolver:{" "}
        <strong data-testid="kyb-screening-blocking-count">{data.blocking_hits}</strong> ·
        Aprobación deshabilitada mientras haya bloqueantes pendientes.
      </p>
      {data.groups.map((g: any) => (
        <div key={`${g.subject_type}-${g.subject_id}`}
             className="bg-surface border border-border rounded-xl p-4"
             data-testid={`kyb-screening-group-${g.subject_type}-${g.subject_id}`}>
          <p className="text-sm font-medium text-fg">
            {g.subject_name || g.subject_id}
            <span className="ml-2 text-xs text-fg-muted font-mono">{g.subject_type}</span>
          </p>
          {g.hits.length === 0 ? (
            <p className="mt-2 text-xs text-fg-muted">Sin hits.</p>
          ) : g.hits.map((h: any) => <HitCard key={h.hit_id} h={h} busy={busy}
            onResolve={resolve} onToggleBlock={toggleBlock} />)}
        </div>))}
    </div>
  );
}

function HitCard({ h, busy, onResolve, onToggleBlock }: any) {
  const [notes, setNotes] = useState("");
  const [reason, setReason] = useState("");
  const resolved = !!h.resolution?.decision;
  return (
    <div className={`mt-2 rounded-lg border border-border p-3 text-sm ${
        h.is_blocking && !resolved ? "border-danger/50 bg-danger/5" : ""}`}
         data-testid={`kyb-hit-${h.hit_id}`}>
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="font-mono text-xs text-fg-muted">{h.list_type}</span>
        <span className="text-fg">{h.list_name}</span>
        <span className="text-fg-muted">→ {h.matched_name || "—"}</span>
        {h.match_score != null && <span className="text-xs text-fg-muted">
          ({h.match_score})</span>}
        <span className={`text-[10px] px-1.5 py-0.5 rounded ${
            h.source === "provider" ? "bg-primary/15 text-primary"
            : "bg-warning/15 text-warning"}`}>{h.source}</span>
        {h.is_blocking && <span className="text-[10px] px-1.5 py-0.5 rounded bg-danger/15 text-danger">
          bloqueante</span>}
        {h.detected_after_approval && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-danger/20 text-danger font-bold"
                data-testid={`kyb-hit-post-approval-${h.hit_id}`}>
            detectado tras aprobación</span>)}
      </div>
      {resolved && (
        <p className="mt-1 text-xs text-fg-muted"
           data-testid={`kyb-hit-resolution-${h.hit_id}`}>
          Resuelto como <strong>{h.resolution.decision === "confirmed"
          ? "coincidencia real" : "falso positivo"}</strong> por{" "}
          <span className="font-mono">{h.resolution.by}</span> el{" "}
          {h.resolution.at?.slice(0, 19)} — {h.resolution.notes}
          {h.provider_sync && (
            <span className="ml-1 text-[10px]"
                  data-testid={`kyb-hit-sync-${h.hit_id}`}>
              · sync proveedor: {h.provider_sync.pending ? "pendiente" :
                h.provider_sync.last_error ? "fallo (reintentando)" : "ok"}</span>)}
        </p>)}
      {!resolved && (
        <>
          <textarea className="mt-2 w-full rounded border border-border bg-bg px-2 py-1 text-xs"
                    rows={2} placeholder="Nota (mín. 20 caracteres)"
                    value={notes} onChange={(e) => setNotes(e.target.value)}
                    data-testid={`kyb-hit-notes-${h.hit_id}`} />
          <div className="mt-1 flex flex-wrap gap-2">
            <button className="rounded border border-danger/50 text-danger px-2 py-1 text-xs disabled:opacity-40"
                    disabled={busy === h.hit_id || notes.trim().length < 20}
                    data-testid={`kyb-hit-confirm-${h.hit_id}`}
                    onClick={() => onResolve(h.hit_id, "confirmed", notes)}>
              Coincidencia real</button>
            <button className="rounded border border-border px-2 py-1 text-xs disabled:opacity-40"
                    disabled={busy === h.hit_id || notes.trim().length < 20}
                    data-testid={`kyb-hit-fp-${h.hit_id}`}
                    onClick={() => onResolve(h.hit_id, "false_positive", notes)}>
              Falso positivo</button>
            <input className="flex-1 rounded border border-border bg-bg px-2 py-1 text-xs"
                   placeholder="Motivo para (des)bloquear (mín. 10)"
                   value={reason} onChange={(e) => setReason(e.target.value)}
                   data-testid={`kyb-hit-blockreason-${h.hit_id}`} />
            <button className="rounded border border-warning/50 text-warning px-2 py-1 text-xs disabled:opacity-40"
                    disabled={busy === h.hit_id || reason.trim().length < 10}
                    data-testid={`kyb-hit-toggle-block-${h.hit_id}`}
                    onClick={() => onToggleBlock(h.hit_id, h.is_blocking, reason)}>
              {h.is_blocking ? "Quitar bloqueo" : "Marcar bloqueante"}</button>
          </div>
        </>)}
    </div>
  );
}

function RegistryTab({ caseId, reload }: { caseId: string; reload: () => void }) {
  const [data, setData] = useState<any>(null);
  const [busy, setBusy] = useState("");
  const load = useCallback(() => api<any>(`${BASE}/cases/${caseId}/registry`)
    .then(setData).catch((e) => toast.error(e?.message)), [caseId]);
  useEffect(() => { load(); }, [load]);
  if (!data) return <p className="text-sm text-fg-muted">Cargando…</p>;
  const isNotFound = !data.provider_outcome && data.mode !== "manual";

  async function act(field: string, action: string, notes: string) {
    setBusy(field);
    try {
      await api(`${BASE}/cases/${caseId}/registry/${field}/accept`,
        { method: "POST", body: JSON.stringify({ action, notes }) });
      toast.success(action === "accept" ? "Diferencia aceptada" : "Observado");
      await load(); reload();
    } catch (e: any) { toast.error(e?.message); }
    finally { setBusy(""); }
  }

  return (
    <div className="space-y-3" data-testid="kyb-registry-tab">
      <p className="text-xs text-fg-muted">
        Modo: <span className="font-mono">{data.mode}</span> · Fuente verificada:{" "}
        <span className="font-mono">{data.verified_source}</span>
      </p>
      {data.mode === "manual" && (
        <div className="rounded-lg border border-border bg-bg/50 p-3 text-xs text-fg-muted"
             data-testid="kyb-registry-manual-banner">
          Esta jurisdicción se verifica por checklist manual. Los valores del
          registro se toman de las notas del checklist company_registry — cada
          ítem del checklist se mapea a un campo por su <code>item_key</code>.
        </div>)}
      {isNotFound && (
        <div className="rounded-lg border border-border bg-bg/50 p-3 text-xs text-fg-muted"
             data-testid="kyb-registry-notfound-banner">
          No hay cobertura automática para esta jurisdicción. La verificación se
          realiza por checklist manual — no se trata de un error ni una bandera
          adversa.
        </div>)}
      <table className="w-full text-sm rounded-xl border border-border overflow-hidden">
        <thead className="bg-bg text-left text-xs text-fg-muted">
          <tr>{["Campo", "Declarado", "Verificado", "Estado", "Acción"].map((h) =>
            <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-border bg-surface">
          {data.fields.map((f: any) => <RegistryRow key={f.field} f={f} busy={busy}
                                                    onAct={act} />)}
        </tbody>
      </table>
    </div>
  );
}

function RegistryRow({ f, busy, onAct }: any) {
  const [notes, setNotes] = useState("");
  const [expanded, setExpanded] = useState(false);
  const statusClass =
    f.match === true ? "text-success" :
    f.match === false ? "text-danger" : "text-fg-muted";
  const statusLabel =
    f.review?.action ? `${f.review.action} por ${f.review.by}` :
    f.match === true ? "coincide" :
    f.match === false ? "diferencia" : "sin dato";
  return (
    <>
      <tr data-testid={`kyb-registry-row-${f.field}`}>
        <td className="px-3 py-2 font-mono text-xs">{f.field}</td>
        <td className="px-3 py-2">{f.declared || "—"}</td>
        <td className="px-3 py-2">{f.verified || "—"}</td>
        <td className={`px-3 py-2 text-xs ${statusClass}`}>{statusLabel}</td>
        <td className="px-3 py-2">
          <button className="text-primary text-xs hover:underline"
                  data-testid={`kyb-registry-toggle-${f.field}`}
                  onClick={() => setExpanded(!expanded)}>
            {expanded ? "Cerrar" : "Revisar"}</button>
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={5} className="bg-bg/30 px-3 py-2">
            <textarea className="w-full rounded border border-border bg-bg px-2 py-1 text-xs"
                      rows={2} placeholder="Nota (mín. 10 caracteres)"
                      value={notes} onChange={(e) => setNotes(e.target.value)}
                      data-testid={`kyb-registry-notes-${f.field}`} />
            <div className="mt-1 flex gap-2">
              <button className="rounded border border-border px-2 py-1 text-xs disabled:opacity-40"
                      disabled={busy === f.field || notes.trim().length < 10}
                      data-testid={`kyb-registry-accept-${f.field}`}
                      onClick={() => onAct(f.field, "accept", notes)}>
                Aceptar diferencia</button>
              <button className="rounded border border-warning/50 text-warning px-2 py-1 text-xs disabled:opacity-40"
                      disabled={busy === f.field || notes.trim().length < 10}
                      data-testid={`kyb-registry-observe-${f.field}`}
                      onClick={() => onAct(f.field, "observe", notes)}>
                Observar al cliente</button>
            </div>
            {f.review && (
              <p className="mt-1 text-[11px] text-fg-muted">
                Revisión previa: {f.review.action} · {f.review.notes} · por{" "}
                <span className="font-mono">{f.review.by}</span> el{" "}
                {f.review.at?.slice(0, 19)}</p>)}
          </td>
        </tr>)}
    </>
  );
}
