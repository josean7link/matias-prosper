"use client";
/* Fase 6 — Pestaña Verificación manual (absorbe la vista provisional 5a). */
import { useCallback, useEffect, useRef, useState } from "react";
import { ExternalLink, FileUp, Users } from "lucide-react";
import { toast } from "sonner";
import { getCaseChecks, generateChecks, patchItem, completeCheck,
         uploadEvidence, discardEvidence, CATEGORY_LABELS, SUBJECT_LABELS,
         type CaseChecks, type EvidenceDoc,
         type ManualCheck } from "@/lib/kyb-manual";

export function ManualChecksTab({ caseId }: { caseId: string }) {
  const [data, setData] = useState<CaseChecks | null>(null);
  const load = useCallback(() => getCaseChecks(caseId).then(setData)
    .catch((e) => toast.error(e?.message)), [caseId]);
  useEffect(() => { load(); }, [load]);
  if (!data) return <p className="text-sm text-fg-muted">Cargando…</p>;
  const total = data.checks.reduce((a, c) => a + c.items.length, 0);
  const done = data.checks.reduce((a, c) => a + c.items.filter((i) => i.outcome).length, 0);
  const contributors = Array.from(new Set(data.checks.flatMap((c) => c.contributors)));
  return (
    <div data-testid="kyb-manual-tab">
      <div className="flex items-center gap-3 mb-3">
        <div className="flex-1 h-1.5 rounded bg-surface overflow-hidden border border-border">
          <div className="h-full bg-primary" style={{ width: total ? `${(done / total) * 100}%` : "0%" }} />
        </div>
        <span className="text-xs font-mono text-fg-muted" data-testid="kyb-global-progress">{done}/{total} ítems</span>
        <button className="rounded-lg bg-primary text-white px-3 py-1.5 text-xs hover:opacity-90"
                data-testid="kyb-generate-checks-button"
                onClick={() => generateChecks(caseId).then((r: any) => {
                  toast.success(`${r.created} checklist(s) generados`); load(); })
                  .catch((e) => toast.error(e?.message))}>Generar checklists</button>
      </div>
      {contributors.length > 0 && (
        <p className="text-xs text-fg-muted mb-3 flex items-center gap-1.5"
           data-testid="kyb-contributors-warning">
          <Users size={12} /> Verificadores participantes (no podrán aprobar
          este caso — maker-checker): <span className="font-mono">{contributors.join(", ")}</span></p>)}
      {data.checks.length === 0 ? (
        <p className="text-sm text-fg-muted rounded-xl border-2 border-dashed border-border p-8 text-center"
           data-testid="kyb-no-checks">Sin checklists todavía.</p>
      ) : (
        <div className="space-y-4">
          {data.checks.map((c) => (
            <CheckBlock key={c.check_id} check={c} reload={load}
                        evidenceDocs={data.evidence_documents || []} />))}
        </div>)}
    </div>
  );
}

function CheckBlock({ check, reload, evidenceDocs }: {
  check: ManualCheck; reload: () => Promise<any>;
  evidenceDocs: EvidenceDoc[] }) {
  const done = check.items.filter((i) => i.outcome).length;
  const complete = check.status === "completed";
  async function markComplete() {
    try {
      await completeCheck(check.check_id);
      toast.success("Verificación completa registrada");
      await reload();
    } catch (e: any) { toast.error(e?.message || "Error"); }
  }
  return (
    <div className="bg-surface border border-border rounded-2xl p-5"
         data-testid={`kyb-check-${check.check_id}`}>
      <div className="flex items-center gap-3 mb-1">
        <div className="flex-1">
          <p className="text-sm font-semibold text-fg">
            {SUBJECT_LABELS[check.subject_type]} — {check.subject_name}</p>
          <p className="text-xs text-fg-muted">
            {CATEGORY_LABELS[check.category]} · plantilla{" "}
            <span className="font-mono">{check.template_id} v{check.template_version}</span>
            {" "}· disparador: {check.trigger}</p>
        </div>
        <span className={`text-xs font-mono px-2 py-1 rounded-full border ${
          complete ? "text-success border-success/40 bg-success/10"
                   : "text-fg-muted border-border"}`}
              data-testid={`kyb-check-progress-${check.check_id}`}>
          {complete ? "completada" : `${done}/${check.items.length}`}</span>
      </div>
      {check.contributors.length > 0 && (
        <p className="text-[11px] text-fg-muted mb-2">
          Completado por: {check.contributors.join(", ")}</p>)}
      <div className="divide-y divide-border">
        {check.items.map((it) => (
          <ItemRow key={`${it.item_key}:${it.outcome ?? ""}:${(it.evidence_document_ids || []).length}`}
                   check={check} item={it}
                   readOnly={complete} reload={reload}
                   evidenceDocs={evidenceDocs} />))}
      </div>
      {!complete && done === check.items.length && check.items.length > 0 && (
        <button className="mt-4 w-full rounded-lg bg-primary text-white py-2.5 text-sm hover:opacity-90"
                data-testid={`kyb-check-complete-${check.check_id}`}
                onClick={markComplete}>Marcar verificación completa</button>)}
    </div>
  );
}

function ItemRow({ check, item, readOnly, reload, evidenceDocs }: {
  check: ManualCheck; item: ManualCheck["items"][number];
  readOnly: boolean; reload: () => Promise<any>;
  evidenceDocs: EvidenceDoc[] }) {
  const [outcome, setOutcome] = useState(item.outcome || "");
  const [notes, setNotes] = useState(item.notes || "");
  const [evidence, setEvidence] = useState<string[]>(item.evidence_document_ids || []);
  const [busy, setBusy] = useState(false);
  const [discarding, setDiscarding] = useState<string | null>(null);
  const [discardReason, setDiscardReason] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const myDocs = evidenceDocs.filter((d) => evidence.includes(d.document_id));

  async function discard() {
    if (!discarding) return;
    try {
      const r = await discardEvidence(check.check_id, discarding, discardReason);
      toast.success(r.reset_items.length
        ? "Evidencia descartada — el ítem debe completarse de nuevo"
        : "Evidencia descartada");
      setDiscarding(null); setDiscardReason("");
      setEvidence((e) => e.filter((id) => id !== discarding));
      await reload();
    } catch (e: any) { toast.error(e?.message || "Error al descartar"); }
  }

  async function upload(f: File) {
    setBusy(true);
    try {
      const r = await uploadEvidence(check.check_id, item.item_key, f);
      setEvidence((e) => [...e, r.document_id]);
      toast.success("Evidencia cargada");
    } catch (e: any) { toast.error(e?.message || "Error al subir"); }
    finally { setBusy(false); }
  }
  async function save() {
    try {
      await patchItem(check.check_id, item.item_key,
        { outcome, notes, evidence_document_ids: evidence });
      toast.success("Ítem guardado");
      await reload();
    } catch (e: any) { toast.error(e?.message || "Error al guardar"); }
  }
  return (
    <div className="py-3" data-testid={`kyb-item-${check.check_id}-${item.item_key}`}>
      <div className="flex items-start gap-2">
        <div className="flex-1">
          <p className="text-sm text-fg font-medium">{item.label}
            {item.evidence_required &&
              <span className="ml-1.5 text-[10px] text-warning">evidencia obligatoria</span>}</p>
          {item.description && <p className="text-xs text-fg-muted mt-0.5">{item.description}</p>}
          {item.source_url && (
            <a href={item.source_url} target="_blank" rel="noreferrer"
               className="text-xs text-primary hover:underline inline-flex items-center gap-1 mt-0.5"
               data-testid={`kyb-item-source-${item.item_key}`}>
              <ExternalLink size={11} /> Fuente</a>)}
        </div>
        {item.completed_by && (
          <span className="text-[10px] text-fg-muted font-mono shrink-0"
                data-testid={`kyb-item-by-${item.item_key}`}>
            ✓ {item.completed_by}</span>)}
      </div>
      {!readOnly && (
        <div className="mt-2 grid grid-cols-1 sm:grid-cols-[140px_1fr_auto_auto] gap-2 items-start">
          <select className="rounded-lg border border-border bg-bg px-2.5 py-2 text-sm text-fg"
                  value={outcome} data-testid={`kyb-item-outcome-${item.item_key}`}
                  onChange={(e) => setOutcome(e.target.value)}>
            <option value="">Resultado…</option>
            {item.possible_outcomes.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
          <input className="rounded-lg border border-border bg-bg px-3 py-2 text-sm text-fg"
                 placeholder="Notas del verificador (mín. 10 caracteres)"
                 value={notes} data-testid={`kyb-item-notes-${item.item_key}`}
                 onChange={(e) => setNotes(e.target.value)} />
          <button className="rounded-lg border border-border px-3 py-2 text-xs text-fg hover:bg-bg flex items-center gap-1"
                  data-testid={`kyb-item-evidence-${item.item_key}`}
                  onClick={() => fileRef.current?.click()}>
            <FileUp size={12} /> {busy ? "Subiendo…" : `Evidencia (${evidence.length})`}
          </button>
          <button className="rounded-lg bg-primary text-white px-4 py-2 text-xs hover:opacity-90 disabled:opacity-50"
                  disabled={!outcome || notes.trim().length < 10}
                  data-testid={`kyb-item-save-${item.item_key}`}
                  onClick={save}>Guardar</button>
          <input ref={fileRef} type="file" className="hidden"
                 data-testid={`kyb-item-file-${item.item_key}`}
                 onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
        </div>)}
      {!readOnly && myDocs.length > 0 && (
        <div className="mt-1.5 space-y-1" data-testid={`kyb-item-evidence-list-${item.item_key}`}>
          {myDocs.map((d) => (
            <div key={d.document_id} className="flex items-center gap-2 text-[11px] text-fg-muted">
              <span className="font-mono truncate">{d.filename}</span>
              {discarding === d.document_id ? (
                <>
                  <input className="rounded border border-border bg-bg px-2 py-1 text-[11px] text-fg flex-1"
                         placeholder="Motivo del descarte (mín. 10 caracteres)"
                         value={discardReason} autoFocus
                         data-testid={`kyb-discard-reason-${item.item_key}`}
                         onChange={(e) => setDiscardReason(e.target.value)} />
                  <button className="text-danger hover:underline disabled:opacity-50"
                          disabled={discardReason.trim().length < 10}
                          data-testid={`kyb-discard-confirm-${item.item_key}`}
                          onClick={discard}>Confirmar</button>
                  <button className="hover:underline"
                          onClick={() => { setDiscarding(null); setDiscardReason(""); }}>
                    Cancelar</button>
                </>
              ) : (
                <button className="text-danger hover:underline"
                        data-testid={`kyb-discard-btn-${d.document_id}`}
                        onClick={() => setDiscarding(d.document_id)}>Descartar</button>
              )}
            </div>))}
        </div>)}
      {readOnly && item.outcome && (
        <p className="text-xs text-fg-muted mt-1">
          Resultado: <span className="font-mono">{item.outcome}</span> — {item.notes}</p>)}
    </div>
  );
}
