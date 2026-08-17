"use client";
/* Fase 4 — Subsección de beneficiarios finales (UBO) + DDJJ del cuadro. */
import { useRef, useState } from "react";
import { Pencil, Plus, Trash2, UploadCloud, UserCheck } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { inputCls, labelCls, buttonCls } from "../_components/KybShell";
import type { CaseData } from "./page";

type P = { data: CaseData; reload: () => Promise<void>; editable: boolean };

const EMPTY = {
  control_type: "OWNERSHIP", first_name: "", last_name: "", birth_date: "",
  nationality: "AR", address: "", marital_status: "", profession: "",
  phone: "", email: "", document_number: "", tax_id: "",
  ownership_percentage: "", relationship_start_date: "",
  is_obliged_subject: false, is_pep: false,
  document_front_id: "", document_back_id: "",
};

export function UboSection({ data, reload, editable }: P) {
  const ubos = data.ubos || [];
  const confirmed =
    data.case.sections?.documentation?.slots?.beneficial_owners === "confirmed";
  const [ddjj, setDdjj] = useState(false);
  const [form, setForm] = useState<null | { ubo?: any; controlBody: boolean }>(null);
  const [pctModal, setPctModal] = useState<number | null>(null);

  const total = ubos
    .filter((u: any) => u.control_type === "OWNERSHIP")
    .reduce((a: number, u: any) => a + (u.ownership_percentage || 0), 0);

  async function confirm(ack = false) {
    try {
      await api("/v1/kyb/case/ubos/confirm", { method: "POST",
        body: JSON.stringify({ declaration: true, acknowledge_incomplete: ack }) });
      setPctModal(null);
      toast.success("Cuadro societario confirmado");
      await reload();
    } catch (e: any) {
      if (e instanceof ApiError && e.status === 409) setPctModal(Math.round(total * 100) / 100);
      else toast.error(e?.message || "No se pudo confirmar");
    }
  }
  async function remove(id: string) {
    try {
      await api(`/v1/kyb/case/ubos/${id}`, { method: "DELETE" });
      toast.success("Beneficiario eliminado");
      await reload();
    } catch (e: any) { toast.error(e?.message); }
  }

  return (
    <div className="bg-surface border border-border rounded-2xl p-6 mb-4"
         data-testid="kyb-ubo-section">
      <h2 className="text-base font-semibold text-fg mb-4">
        Beneficiarios finales {confirmed && "✓"}</h2>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Izquierda: normativa PLAFT + DDJJ */}
        <div>
          <div className="rounded-lg bg-bg border border-border p-4 text-sm text-fg-muted space-y-2"
               data-testid="kyb-ubo-plaft-text">
            <p>De acuerdo con la normativa vigente en materia de Prevención de
            Lavado de Activos y Financiamiento del Terrorismo (Ley 25.246,
            Resolución UIF 112/2021 y modificatorias), se considera
            <strong className="text-fg"> beneficiario final</strong> a toda persona humana que posea,
            directa o indirectamente, al menos el <strong className="text-fg">diez por ciento
            (10%)</strong> del capital o de los derechos de voto de la persona
            jurídica, o que por otros medios ejerza su control final.</p>
            <p>Si ninguna persona humana alcanza dicho umbral, deberá
            identificarse a quienes ejerzan la administración o el órgano de
            control de la sociedad.</p>
          </div>
          <label className="flex items-start gap-2 mt-4 text-sm text-fg">
            <input type="checkbox" checked={ddjj} disabled={!editable || confirmed}
                   className="mt-0.5" data-testid="kyb-ubo-ddjj-checkbox"
                   onChange={(e) => setDdjj(e.target.checked)} />
            <span>Declaro bajo juramento que la información sobre los
            beneficiarios finales consignada en este expediente es veraz,
            completa y se encuentra actualizada.</span>
          </label>
          <button className={buttonCls + " mt-4"}
                  disabled={!editable || confirmed || !ddjj || ubos.length === 0}
                  data-testid="kyb-ubo-confirm-button"
                  onClick={() => confirm(false)}>
            Confirmar cuadro societario</button>
          {confirmed && (
            <p className="text-xs text-success mt-2" data-testid="kyb-ubo-confirmed-note">
              ✓ Cuadro confirmado con declaración jurada. Cualquier alta, baja
              o edición posterior requerirá una nueva confirmación.</p>)}
        </div>
        {/* Derecha: lista */}
        <div>
          {ubos.length === 0 ? (
            <div className="rounded-xl border-2 border-dashed border-border p-8 text-center"
                 data-testid="kyb-ubo-empty-state">
              <p className="text-sm text-fg-muted">Todavía no cargaste
              beneficiarios finales.</p>
            </div>
          ) : (
            <div className="space-y-2" data-testid="kyb-ubo-list">
              {ubos.map((u: any) => (
                <div key={u.ubo_id}
                     className="flex items-center gap-3 rounded-lg border border-border bg-bg px-3 py-2.5 text-sm"
                     data-testid={`kyb-ubo-row-${u.ubo_id}`}>
                  <div className="flex-1 min-w-0">
                    <p className="text-fg truncate">{u.first_name} {u.last_name}
                      {u.is_also_legal_representative && (
                        <span className="ml-1.5 inline-flex items-center gap-1 text-xs text-primary"
                              title="Coincide con el representante legal (mismo CUIT/CUIL)"
                              data-testid={`kyb-ubo-alsorep-${u.ubo_id}`}>
                          <UserCheck size={12} /> Rep. legal</span>)}
                    </p>
                    <p className="text-xs text-fg-muted">
                      {u.control_type === "CONTROL_BODY"
                        ? "Órgano de administración / control"
                        : `${u.ownership_percentage}% de participación`}
                      {u.is_pep && " · PEP"}</p>
                  </div>
                  {editable && (<>
                    <button className="text-fg-muted hover:text-primary p-1"
                            data-testid={`kyb-ubo-edit-${u.ubo_id}`}
                            onClick={() => setForm({ ubo: u,
                              controlBody: u.control_type === "CONTROL_BODY" })}>
                      <Pencil size={14} /></button>
                    <button className="text-danger hover:bg-danger/10 rounded p-1"
                            data-testid={`kyb-ubo-delete-${u.ubo_id}`}
                            onClick={() => remove(u.ubo_id)}>
                      <Trash2 size={14} /></button>
                  </>)}
                </div>))}
              <p className="text-xs text-fg-muted pt-1" data-testid="kyb-ubo-total">
                Participación declarada: {Math.round(total * 100) / 100}%</p>
            </div>
          )}
          {editable && (
            <div className="mt-3 space-y-2">
              <button className="w-full rounded-lg border border-primary/50 text-primary py-2.5 text-sm hover:bg-primary/10 flex items-center justify-center gap-1.5"
                      data-testid="kyb-ubo-add-button"
                      onClick={() => setForm({ controlBody: false })}>
                <Plus size={15} /> Añadir beneficiario</button>
              <button className="w-full rounded-lg border border-border text-fg-muted py-2.5 text-xs hover:bg-bg"
                      data-testid="kyb-ubo-control-body-button"
                      onClick={() => setForm({ controlBody: true })}>
                No hay socios que alcancen el 10% de participación
                (declarar órgano de control)</button>
            </div>)}
        </div>
      </div>

      {form && (
        <UboFormModal data={data} ubo={form.ubo} controlBody={form.controlBody}
                      onClose={() => setForm(null)}
                      onSaved={async () => { setForm(null); await reload(); }} />)}

      {pctModal !== null && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
             data-testid="kyb-ubo-incomplete-modal">
          <div className="bg-surface border border-border rounded-2xl p-6 max-w-md w-full">
            <h2 className="text-lg font-semibold text-fg mb-2">Cuadro societario incompleto</h2>
            <p className="text-sm text-fg-muted mb-6" data-testid="kyb-ubo-incomplete-text">
              Los beneficiarios cargados suman el <strong className="text-fg">{pctModal}%</strong> de
              la participación societaria. Podés seguir cargando beneficiarios
              hasta completar el 100%, o continuar así: la diferencia quedará
              registrada como una observación visible para el analista.</p>
            <div className="flex gap-3">
              <button className="flex-1 rounded-lg border border-border py-2.5 text-sm text-fg hover:bg-bg"
                      data-testid="kyb-ubo-keep-loading-button"
                      onClick={() => setPctModal(null)}>Seguir cargando</button>
              <button className="flex-1 rounded-lg bg-primary text-white py-2.5 text-sm hover:opacity-90"
                      data-testid="kyb-ubo-continue-anyway-button"
                      onClick={() => confirm(true)}>Sí, continuar</button>
            </div>
          </div>
        </div>)}
    </div>
  );
}

function UboFormModal({ data, ubo, controlBody, onClose, onSaved }: {
  data: CaseData; ubo?: any; controlBody: boolean;
  onClose: () => void; onSaved: () => Promise<void>;
}) {
  const [step, setStep] = useState(1);
  const [f, setF] = useState<any>(ubo
    ? { ...EMPTY, ...Object.fromEntries(Object.entries(ubo)
        .filter(([k]) => k in EMPTY)
        .map(([k, v]) => [k, v ?? EMPTY[k as keyof typeof EMPTY]])) }
    : { ...EMPTY, control_type: controlBody ? "CONTROL_BODY" : "OWNERSHIP" });
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: any) => setF((o: any) => ({ ...o, [k]: v }));
  const isCB = f.control_type === "CONTROL_BODY";

  const step1Ok = f.first_name.trim() && f.last_name.trim();
  const pct = f.ownership_percentage === "" ? null : Number(f.ownership_percentage);
  const pctOk = isCB || (pct !== null && pct >= 0 && pct <= 100
    && Math.round(pct * 100) / 100 === pct);
  const step2Ok = pctOk && !!f.document_front_id;

  async function save() {
    setBusy(true);
    try {
      const body = { ...f, ownership_percentage: isCB ? null : pct,
        document_back_id: f.document_back_id || null };
      if (ubo) await api(`/v1/kyb/case/ubos/${ubo.ubo_id}`,
        { method: "PUT", body: JSON.stringify(body) });
      else await api("/v1/kyb/case/ubos",
        { method: "POST", body: JSON.stringify(body) });
      toast.success(ubo ? "Beneficiario actualizado" : "Beneficiario agregado");
      await onSaved();
    } catch (e: any) { toast.error(e?.message || "Error al guardar"); }
    finally { setBusy(false); }
  }

  const txt = (k: string, lbl: string, type = "text", ph = "") => (
    <div><label className={labelCls}>{lbl}</label>
      <input type={type} value={f[k]} className={inputCls} placeholder={ph}
             data-testid={`kyb-ubo-form-${k}`}
             onChange={(e) => set(k, e.target.value)} /></div>);

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4 overflow-y-auto"
         data-testid="kyb-ubo-form-modal">
      <div className="bg-surface border border-border rounded-2xl p-6 max-w-lg w-full my-8">
        <div className="flex items-center justify-between mb-1">
          <h2 className="text-lg font-semibold text-fg">
            {ubo ? "Editar beneficiario" : isCB
              ? "Declarar órgano de control" : "Añadir beneficiario"}</h2>
          <span className="text-xs text-fg-muted" data-testid="kyb-ubo-form-step">
            Paso {step} de 2</span>
        </div>
        <p className="text-xs text-fg-muted mb-4">
          {step === 1 ? "Datos personales"
            : "Datos societarios y documento de identidad"}</p>
        {isCB && step === 1 && (
          <p className="text-xs text-fg-muted rounded-lg bg-bg border border-border p-3 mb-4"
             data-testid="kyb-ubo-cb-note">
            Ningún socio alcanza el 10% de participación: identificá a quien
            ejerce la administración u órgano de control de la sociedad.</p>)}

        {step === 1 ? (
          <div className="grid grid-cols-2 gap-3">
            {txt("first_name", "Nombre")}
            {txt("last_name", "Apellido")}
            {txt("birth_date", "Fecha de nacimiento", "date")}
            {txt("nationality", "Nacionalidad (ISO-2)")}
            <div className="col-span-2">{txt("address", "Domicilio")}</div>
            {txt("marital_status", "Estado civil")}
            {txt("profession", "Profesión")}
            {txt("phone", "Teléfono")}
            {txt("email", "Email", "email")}
          </div>
        ) : (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              {txt("document_number", "Número de documento")}
              {txt("tax_id", "CUIT / CUIL", "text", "20-12345678-3")}
              {!isCB && txt("ownership_percentage", "Participación (%)", "number")}
              {txt("relationship_start_date", "Inicio de la relación", "date")}
            </div>
            {!isCB && pct !== null && !pctOk && (
              <p className="text-xs text-danger" data-testid="kyb-ubo-pct-error">
                El porcentaje debe estar entre 0 y 100, con hasta dos decimales.</p>)}
            <label className="flex items-center gap-2 text-sm text-fg">
              <input type="checkbox" checked={f.is_obliged_subject}
                     data-testid="kyb-ubo-form-obliged"
                     onChange={(e) => set("is_obliged_subject", e.target.checked)} />
              Es sujeto obligado ante la UIF</label>
            <label className="flex items-center gap-2 text-sm text-fg">
              <input type="checkbox" checked={f.is_pep}
                     data-testid="kyb-ubo-form-pep"
                     onChange={(e) => set("is_pep", e.target.checked)} />
              Es Persona Expuesta Políticamente (PEP)</label>
            <UboDocUpload label="Documento de identidad — frente (obligatorio)"
                          slot="ubo_document_front" uboId={ubo?.ubo_id}
                          docId={f.document_front_id} data={data}
                          onUploaded={(id) => set("document_front_id", id)} />
            <UboDocUpload label="Documento de identidad — dorso (opcional)"
                          slot="ubo_document_back" uboId={ubo?.ubo_id}
                          docId={f.document_back_id} data={data}
                          onUploaded={(id) => set("document_back_id", id)} />
          </div>
        )}

        <div className="flex gap-3 mt-6">
          <button className="flex-1 rounded-lg border border-border py-2.5 text-sm text-fg hover:bg-bg"
                  data-testid="kyb-ubo-form-cancel"
                  onClick={() => (step === 2 ? setStep(1) : onClose())}>
            {step === 2 ? "Atrás" : "Cancelar"}</button>
          {step === 1 ? (
            <button className={buttonCls + " flex-1"} disabled={!step1Ok}
                    data-testid="kyb-ubo-form-next"
                    onClick={() => setStep(2)}>Siguiente</button>
          ) : (
            <button className={buttonCls + " flex-1"} disabled={!step2Ok || busy}
                    data-testid="kyb-ubo-form-save"
                    onClick={save}>{busy ? "Guardando…" : "Guardar"}</button>)}
        </div>
      </div>
    </div>
  );
}

function UboDocUpload({ label, slot, uboId, docId, data, onUploaded }: {
  label: string; slot: string; uboId?: string; docId: string;
  data: CaseData; onUploaded: (id: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLInputElement>(null);
  const doc = data.documents.find((d) => d.document_id === docId);
  async function upload(file: File) {
    setBusy(true);
    const fd = new FormData();
    fd.append("slot", slot); fd.append("file", file);
    if (uboId) fd.append("ubo_id", uboId);
    try {
      const r = await api<any>("/v1/kyb/case/documents", { method: "POST", body: fd });
      onUploaded(r.document_id);
      toast.success("Documento cargado");
    } catch (e: any) { toast.error(e?.message || "Error al subir"); }
    finally { setBusy(false); }
  }
  return (
    <div>
      <label className={labelCls}>{label}</label>
      <div className="rounded-lg border-2 border-dashed border-border p-3 text-center cursor-pointer hover:border-primary/60 text-sm"
           data-testid={`kyb-ubo-upload-${slot}`}
           onClick={() => ref.current?.click()}>
        <UploadCloud size={16} className="mx-auto text-fg-muted mb-1" />
        <p className="text-xs text-fg-muted">
          {busy ? "Subiendo…" : docId
            ? `✓ ${doc?.filename || "archivo cargado"}` : "Seleccionar archivo"}</p>
        <input ref={ref} type="file" className="hidden"
               data-testid={`kyb-ubo-file-${slot}`}
               onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
      </div>
    </div>
  );
}
