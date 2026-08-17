"use client";
/* Fase 5a — Plantillas de checklist (solo super_admin server-side).
   Cada guardado crea una versión nueva; los checks en curso conservan
   la versión con la que se generaron. */
import { notFound } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { kybEnabled } from "@/app/kyb/_components/KybShell";
import { getTemplates, saveTemplate, CATEGORY_LABELS,
         type CheckTemplate, type TemplateItem } from "@/lib/kyb-manual";

const EMPTY_ITEM: TemplateItem = { item_key: "", label: "", description: "",
  source_url: null, evidence_required: false,
  possible_outcomes: ["clear", "hit", "unavailable"], order: 0 };

export default function KybTemplatesPage() {
  if (!kybEnabled()) notFound();
  const [tpls, setTpls] = useState<CheckTemplate[] | null>(null);
  const [err, setErr] = useState("");
  const [editing, setEditing] = useState<CheckTemplate | null>(null);

  const load = () => getTemplates().then((r) => setTpls(r.items))
    .catch((e) => setErr(e?.message || "No se pudo cargar"));
  useEffect(() => { load(); }, []);

  if (err) return <p className="p-8 text-sm text-danger" data-testid="kyb-templates-error">{err}</p>;
  if (!tpls) return <p className="p-8 text-sm text-fg-muted">Cargando…</p>;
  const latest = Object.values(tpls.reduce((acc, t) => {
    if (!acc[t.template_id] || acc[t.template_id].version < t.version) acc[t.template_id] = t;
    return acc;
  }, {} as Record<string, CheckTemplate>));

  return (
    <div className="max-w-4xl" data-testid="kyb-templates-page">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-semibold text-fg">Plantillas de checklist manual</h1>
          <p className="text-sm text-fg-muted">Editables sin deploy. Guardar crea una versión nueva.</p>
        </div>
        <button className="rounded-lg bg-primary text-white px-4 py-2 text-sm hover:opacity-90"
                data-testid="kyb-template-new-button"
                onClick={() => setEditing({ template_id: "", category: "screening",
                  country: "AR", subject_types: ["company"], version: 0,
                  active: true, items: [{ ...EMPTY_ITEM }] })}>Nueva plantilla</button>
      </div>
      <div className="space-y-3">
        {latest.map((t) => (
          <div key={t.template_id}
               className="bg-surface border border-border rounded-xl p-4 flex items-center gap-4"
               data-testid={`kyb-template-row-${t.template_id}`}>
            <div className="flex-1">
              <p className="text-sm font-medium text-fg">
                {CATEGORY_LABELS[t.category]} · {t.country || "Todos los países"}
                {!t.active && <span className="ml-2 text-xs text-danger">inactiva</span>}</p>
              <p className="text-xs text-fg-muted font-mono">
                {t.template_id} · v{t.version} · {t.items.length} ítems ·
                sujetos: {t.subject_types.join(", ")}</p>
            </div>
            <button className="rounded-lg border border-border px-3 py-1.5 text-xs text-fg hover:bg-bg"
                    data-testid={`kyb-template-edit-${t.template_id}`}
                    onClick={() => setEditing(t)}>Editar</button>
          </div>))}
      </div>
      {editing && (
        <TemplateEditor tpl={editing} onClose={() => setEditing(null)}
                        onSaved={() => { setEditing(null); load(); }} />)}
    </div>
  );
}

function TemplateEditor({ tpl, onClose, onSaved }: {
  tpl: CheckTemplate; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ ...tpl, items: tpl.items.map((i) => ({ ...i })) });
  const isNew = !tpl.template_id;
  const setItem = (idx: number, k: string, v: any) =>
    setF((o) => ({ ...o, items: o.items.map((it, i) => i === idx ? { ...it, [k]: v } : it) }));
  async function save() {
    try {
      await saveTemplate({ category: f.category, country: f.country || null,
        subject_types: f.subject_types, active: f.active,
        items: f.items.map((i, idx) => ({ ...i, order: idx + 1,
          source_url: i.source_url || null })) },
        isNew ? undefined : tpl.template_id);
      toast.success(isNew ? "Plantilla creada" : "Nueva versión guardada");
      onSaved();
    } catch (e: any) { toast.error(e?.message || "Error al guardar"); }
  }
  const inp = "w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-fg";
  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4 overflow-y-auto"
         data-testid="kyb-template-editor">
      <div className="bg-surface border border-border rounded-2xl p-6 max-w-2xl w-full my-8">
        <h2 className="text-lg font-semibold text-fg mb-4">
          {isNew ? "Nueva plantilla" : `Editar ${tpl.template_id} (crea v${tpl.version + 1})`}</h2>
        <div className="grid grid-cols-3 gap-3 mb-4">
          <select className={inp} value={f.category} data-testid="kyb-tpl-category"
                  onChange={(e) => setF({ ...f, category: e.target.value })}>
            {Object.entries(CATEGORY_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <input className={inp} placeholder="País (ISO-2, vacío = todos)"
                 value={f.country || ""} data-testid="kyb-tpl-country"
                 onChange={(e) => setF({ ...f, country: e.target.value.toUpperCase() || null })} />
          <select className={inp} multiple value={f.subject_types} data-testid="kyb-tpl-subjects"
                  onChange={(e) => setF({ ...f, subject_types:
                    Array.from(e.target.selectedOptions).map((o) => o.value) })}>
            <option value="company">Empresa</option>
            <option value="legal_representative">Rep. legal</option>
            <option value="ubo">UBO</option>
          </select>
        </div>
        <div className="space-y-3 max-h-[45vh] overflow-y-auto pr-1">
          {f.items.map((it, idx) => (
            <div key={idx} className="rounded-lg border border-border p-3 space-y-2"
                 data-testid={`kyb-tpl-item-${idx}`}>
              <div className="grid grid-cols-2 gap-2">
                <input className={inp} placeholder="item_key" value={it.item_key}
                       onChange={(e) => setItem(idx, "item_key", e.target.value)} />
                <input className={inp} placeholder="Etiqueta" value={it.label}
                       onChange={(e) => setItem(idx, "label", e.target.value)} />
              </div>
              <textarea className={inp} rows={2} placeholder="Qué tiene que hacer el verificador"
                        value={it.description}
                        onChange={(e) => setItem(idx, "description", e.target.value)} />
              <div className="grid grid-cols-2 gap-2 items-center">
                <input className={inp} placeholder="URL de la fuente (opcional)"
                       value={it.source_url || ""}
                       onChange={(e) => setItem(idx, "source_url", e.target.value)} />
                <label className="flex items-center gap-2 text-xs text-fg">
                  <input type="checkbox" checked={it.evidence_required}
                         onChange={(e) => setItem(idx, "evidence_required", e.target.checked)} />
                  Evidencia obligatoria</label>
              </div>
              <input className={inp} placeholder="Resultados posibles (coma)"
                     value={it.possible_outcomes.join(",")}
                     onChange={(e) => setItem(idx, "possible_outcomes",
                       e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} />
            </div>))}
        </div>
        <button className="mt-3 text-xs text-primary hover:underline"
                data-testid="kyb-tpl-add-item"
                onClick={() => setF({ ...f, items: [...f.items, { ...EMPTY_ITEM }] })}>
          + Agregar ítem</button>
        <div className="flex gap-3 mt-5">
          <button className="flex-1 rounded-lg border border-border py-2.5 text-sm text-fg hover:bg-bg"
                  data-testid="kyb-tpl-cancel" onClick={onClose}>Cancelar</button>
          <button className="flex-1 rounded-lg bg-primary text-white py-2.5 text-sm hover:opacity-90"
                  data-testid="kyb-tpl-save" onClick={save}>Guardar</button>
        </div>
      </div>
    </div>
  );
}
