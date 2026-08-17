"use client";
/* Fase 3 — Cuerpos de sección del wizard KYB. */
import { useCallback, useEffect, useRef, useState } from "react";
import { UploadCloud, FileText, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { inputCls, labelCls, buttonCls } from "../_components/KybShell";
import { UboSection } from "./ubos";
import type { CaseData } from "./page";

export const SECTIONS_META = [
  { key: "tax_identification", label: "Identificación tributaria" },
  { key: "legal_representative", label: "Representante Legal" },
  { key: "company_data", label: "Datos de la empresa" },
  { key: "documentation", label: "Documentación de la empresa" },
  { key: "team", label: "Gestioná tu equipo (opcional)" },
];

const SLOT_META: Record<string, { title: string; text: string }> = {
  tax_registration_certificate: { title: "Constancia de inscripción fiscal",
    text: "Acompañar la constancia de inscripción fiscal de la compañía emitida por ARCA." },
  constitutive_document: { title: "Instrumento constitutivo",
    text: "Adjunte el instrumento constitutivo de la compañía. Asimismo, se deberá acompañar el estatuto o contrato social vigente, con sus modificaciones y reformas, en caso de corresponder. La documentación presentada deberá permitir identificar de manera clara: 1) El registro de inscripción (IGJ u organismo registral correspondiente). 2) El número y la fecha de inscripción de la persona jurídica." },
  funds_origin_evidence: { title: "Acreditación de origen de fondos",
    text: "Acompañá estados contables, facturas, presentaciones de impuestos, contratos comerciales u otra documentación de respaldo que permita acreditar el origen de los fondos de la compañía." },
  authorities_appointment: { title: "Designación de autoridades",
    text: "Subir un documento que demuestre que la persona registrada como Representante Legal está autorizada a actuar en nombre de la compañía. Se acepta: A) Acta de designación o nombramiento de autoridades. B) Resolución societaria. C) Poder." },
  company_proof_of_address: { title: "Comprobante de domicilio",
    text: "Factura de servicios, extracto bancario, contrato de alquiler vigente y firmado, o documento oficial que acredite el domicilio de la compañía. Si la compañía opera de forma remota, se acepta el comprobante del representante legal." },
};

function cuitDv(digits: string): boolean {
  if (digits.length !== 11) return false;
  const w = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2];
  let dv = 11 - (digits.slice(0, 10).split("")
    .reduce((a, d, i) => a + parseInt(d) * w[i], 0) % 11);
  if (dv === 11) dv = 0; if (dv === 10) dv = 9;
  return dv === parseInt(digits[10]);
}
const maskCuit = (v: string) => {
  const d = v.replace(/\D/g, "").slice(0, 11);
  if (d.length <= 2) return d;
  if (d.length <= 10) return `${d.slice(0, 2)}-${d.slice(2)}`;
  return `${d.slice(0, 2)}-${d.slice(2, 10)}-${d.slice(10)}`;
};

type P = { data: CaseData; reload: () => Promise<void>; editable: boolean;
           setDirty: (d: boolean) => void;
           registerAutosave: (k: string, fn: () => Promise<void>) => void };

function Observation({ data, section }: { data: CaseData; section: string }) {
  const s = data.case.sections?.[section];
  if (!s?.observation || !["observed", "resubmitted"].includes(s?.status)) return null;
  const fixed = s.status === "resubmitted";
  return (
    <div className={`mb-4 rounded-lg border p-3 text-sm text-fg ${
           fixed ? "border-border bg-bg" : "border-warning/40 bg-warning/10"}`}
         data-testid={`kyb-observation-${section}`}>
      <strong>Observación del analista:</strong> {s.observation}
      {fixed && (
        <p className="text-xs text-success mt-1" data-testid={`kyb-resubmitted-note-${section}`}>
          ✓ Corregiste esta sección después de la observación. Queda pendiente
          de re-revisión por el analista.
        </p>
      )}
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-surface border border-border rounded-2xl p-6 mb-4">
      <h2 className="text-base font-semibold text-fg mb-4">{title}</h2>
      {children}
    </div>
  );
}

export function SectionBody(p: P & { active: string }) {
  if (p.active === "tax_identification") return <TaxSection {...p} />;
  if (p.active === "legal_representative") return <RepSection {...p} />;
  if (p.active === "company_data") return <CompanySection {...p} />;
  if (p.active === "documentation") return <DocsSection {...p} />;
  return <TeamSection {...p} />;
}

function TaxSection({ data, reload, editable, setDirty }: P) {
  const locked = data.profile.tax_id_locked;
  const [cuit, setCuit] = useState(maskCuit(data.profile.tax_id || ""));
  const [ok, setOk] = useState(false);
  const digits = cuit.replace(/\D/g, "");
  const valid = cuitDv(digits);
  async function save() {
    try {
      await api("/v1/kyb/case/tax-identification", { method: "PUT",
        body: JSON.stringify({ tax_id: digits,
          accepted_documents: data.legal_docs.map((d) => d.document_key) }) });
      toast.success("Identificación tributaria confirmada");
      setDirty(false); await reload();
    } catch (e: any) { toast.error(e?.message || "Error al guardar"); }
  }
  return (
    <Card title="Identificación tributaria">
      <Observation data={data} section="tax_identification" />
      <div className="mb-4 rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm text-fg"
           data-testid="kyb-cuit-warning">
        <strong>¡Atención!</strong> El número de identificación tributaria no
        podrá ser editado posteriormente.
      </div>
      <label className={labelCls}>CUIT</label>
      <input value={cuit} disabled={locked || !editable} className={inputCls}
             data-testid="kyb-cuit-input" placeholder="30-12345678-0"
             onChange={(e) => { setCuit(maskCuit(e.target.value)); setDirty(true); }} />
      {digits.length === 11 && (
        <p className={`text-xs mt-1 ${valid ? "text-success" : "text-danger"}`}
           data-testid="kyb-cuit-validation">
          {valid ? "Dígito verificador válido" : "Dígito verificador incorrecto"}
        </p>
      )}
      {!locked && (
        <>
          <label className="flex items-start gap-2 mt-5 text-sm text-fg">
            <input type="checkbox" checked={ok} disabled={!editable}
                   data-testid="kyb-legal-accept-checkbox"
                   onChange={(e) => setOk(e.target.checked)} className="mt-0.5" />
            <span>Acepto los{" "}
              {data.legal_docs.map((d, i) => (
                <span key={d.document_key}>
                  {i > 0 && (i === data.legal_docs.length - 1 ? " y " : ", ")}
                  <a href={d.url} target="_blank" className="text-primary hover:underline">
                    {d.title} (v{d.version})</a>
                </span>))}
            </span>
          </label>
          <button onClick={save} disabled={!ok || !valid || !editable}
                  className={buttonCls + " mt-5"}
                  data-testid="kyb-tax-save-button">Guardar</button>
        </>
      )}
      {locked && <p className="text-sm text-fg-muted mt-4" data-testid="kyb-cuit-locked-note">
        CUIT confirmado y bloqueado. La aceptación de legales quedó registrada
        con versión y hash del contenido.</p>}
    </Card>
  );
}

function RepSection({ data, reload, editable, setDirty, registerAutosave }: P) {
  const lr = data.profile.legal_representative || {};
  const [f, setF] = useState({ country_of_residence: lr.country_of_residence || "AR",
    full_name: lr.full_name || "", email: lr.email || "", tax_id: lr.tax_id || "" });
  const dirtyRef = useRef(false);
  const set = (k: string, v: string) => { setF((o) => ({ ...o, [k]: v }));
    dirtyRef.current = true; setDirty(true); };
  useEffect(() => {
    registerAutosave("legal_representative", async () => {
      if (!dirtyRef.current || !f.full_name || !f.email) return;
      await api("/v1/kyb/case/legal-representative", { method: "PUT",
        body: JSON.stringify({ ...f, draft: true }) });
    });
  });
  async function save() {
    try {
      await api("/v1/kyb/case/legal-representative", { method: "PUT",
        body: JSON.stringify(f) });
      toast.success("Representante legal guardado");
      dirtyRef.current = false; setDirty(false); await reload();
    } catch (e: any) { toast.error(e?.message || "Error al guardar"); }
  }
  return (
    <Card title="Representante Legal">
      <Observation data={data} section="legal_representative" />
      <div className="space-y-4">
        <div><label className={labelCls}>País de residencia</label>
          <input value={f.country_of_residence} disabled={!editable}
                 className={inputCls} maxLength={2}
                 data-testid="kyb-rep-country-input"
                 onChange={(e) => set("country_of_residence", e.target.value.toUpperCase())} /></div>
        <div><label className={labelCls}>Nombre y apellido</label>
          <input value={f.full_name} disabled={!editable} className={inputCls}
                 data-testid="kyb-rep-name-input"
                 onChange={(e) => set("full_name", e.target.value)} /></div>
        <div><label className={labelCls}>Correo electrónico</label>
          <input type="email" value={f.email} disabled={!editable}
                 className={inputCls} data-testid="kyb-rep-email-input"
                 onChange={(e) => set("email", e.target.value)} /></div>
        <div><label className={labelCls}>CUIT / CUIL (opcional)</label>
          <input value={f.tax_id} disabled={!editable} className={inputCls}
                 placeholder="20-12345678-3" data-testid="kyb-rep-taxid-input"
                 onChange={(e) => set("tax_id", e.target.value)} />
          <p className="text-xs text-fg-muted mt-1">Si el representante legal
            también es beneficiario final, este dato evita una doble
            verificación de identidad.</p></div>
        <button onClick={save} disabled={!editable} className={buttonCls}
                data-testid="kyb-rep-save-button">Guardar</button>
      </div>
    </Card>
  );
}

function CompanySection(p: P) {
  const prof = p.data.profile;
  const saved = prof.subsections_saved || {};
  const [ln, setLn] = useState({ legal_name: prof.legal_name || "",
    legal_structure: prof.legal_structure || "SA",
    legal_structure_other: prof.legal_structure_other || "" });
  const [cd, setCd] = useState({ activity_description: prof.activity_description || "",
    registration_number: prof.registration_number || "",
    registration_date: prof.registration_date || "", website: prof.website || "" });
  const [ad, setAd] = useState(prof.registered_address ||
    { raw: "", street: "", number: "", city: "", state: "", postal_code: "", country: "AR" });
  const ops = prof.operations || {};
  const [op, setOp] = useState({ estimated_monthly_volume_usd: ops.estimated_monthly_volume_usd ?? "",
    purposes: ops.purposes || [], purpose_other: ops.purpose_other || "",
    funds_subscribed: ops.funds_subscribed || [] });
  const fo0 = prof.funds_origin || {};
  const [fo, setFo] = useState({ type: fo0.type || "", client_funds_ratio: fo0.client_funds_ratio ?? "",
    license_type: fo0.license_type || "", license_number: fo0.license_number || "",
    has_aml_policy: fo0.has_aml_policy ?? null, compliance_officer_name: fo0.compliance_officer_name || "",
    end_user_kyc_description: fo0.end_user_kyc_description || "",
    segregated_assets: fo0.segregated_assets ?? null,
    is_uif_obliged_subject: prof.is_uif_obliged_subject ?? false,
    uif_registration_number: prof.uif_registration_number || "" });
  const mark = () => p.setDirty(true);
  async function put(path: string, body: any, label: string) {
    try {
      await api(`/v1/kyb/case/company/${path}`, { method: "PUT", body: JSON.stringify(body) });
      toast.success(`${label} guardado`); p.setDirty(false); await p.reload();
    } catch (e: any) { toast.error(e?.message || "Error al guardar"); }
  }
  const Chk = ({ on }: { on: boolean }) =>
    on ? <span className="text-xs text-success ml-2">✓ guardado</span> : null;
  const purposesList = [["YIELD_ARS", "Rendimiento sobre saldos en pesos (PROSPER ARS)"],
    ["YIELD_USD", "Rendimiento sobre saldos en dólares (PROSPER USD)"],
    ["EMBEDDED_EARN", "Producto de rendimiento embebido para usuarios finales"],
    ["CORPORATE_TREASURY", "Gestión de tesorería corporativa"],
    ["OTHER", "Otro objetivo"]];
  const showClientBlock = fo.type === "CLIENT_FUNDS" || fo.type === "MIXED";
  return (
    <div>
      <Observation data={p.data} section="company_data" />
      <Card title="Razón Social">
        <Chk on={"legal_name" in saved} />
        <div className="space-y-4">
          <div><label className={labelCls}>Razón social</label>
            <input value={ln.legal_name} disabled={!p.editable} className={inputCls}
                   data-testid="kyb-company-legalname-input"
                   onChange={(e) => { setLn({ ...ln, legal_name: e.target.value }); mark(); }} /></div>
          <div><label className={labelCls}>Estructura legal</label>
            <select value={ln.legal_structure} disabled={!p.editable} className={inputCls}
                    data-testid="kyb-company-structure-select"
                    onChange={(e) => { setLn({ ...ln, legal_structure: e.target.value }); mark(); }}>
              {["SA", "SRL", "SAS", "SAU", "COOPERATIVA", "ASOCIACION_CIVIL", "OTRA"].map((s) =>
                <option key={s} value={s}>{{ SA: "S.A.", SRL: "S.R.L.", SAS: "S.A.S.", SAU: "S.A.U.",
                  COOPERATIVA: "Cooperativa", ASOCIACION_CIVIL: "Asociación Civil", OTRA: "Otra" }[s]}</option>)}
            </select></div>
          {ln.legal_structure === "OTRA" && (
            <input placeholder="Detallá la estructura legal" value={ln.legal_structure_other}
                   className={inputCls} data-testid="kyb-company-structure-other-input"
                   onChange={(e) => { setLn({ ...ln, legal_structure_other: e.target.value }); mark(); }} />)}
          <button className={buttonCls} disabled={!p.editable}
                  data-testid="kyb-company-legalname-save"
                  onClick={() => put("legal-name", ln, "Razón social")}>Guardar</button>
        </div>
      </Card>
      <Card title="Datos de la empresa">
        <Chk on={"data" in saved} />
        <div className="space-y-4">
          <div>
            <label className={labelCls}>Actividad</label>
            <div className="text-xs text-fg-muted mb-2 rounded-lg bg-bg border border-border p-3">
              Contanos: · Actividad que desarrollará la empresa · Generación de
              ingresos · Origen estimado de los fondos
            </div>
            <textarea value={cd.activity_description} disabled={!p.editable} rows={5}
                      maxLength={500} className={inputCls}
                      data-testid="kyb-company-activity-textarea"
                      onChange={(e) => { setCd({ ...cd, activity_description: e.target.value }); mark(); }} />
            <p className="text-xs text-fg-muted mt-1" data-testid="kyb-activity-counter">
              {cd.activity_description.length}/500 caracteres. Mínimo requerido: 100.</p>
          </div>
          <div><label className={labelCls}>Número de inscripción registral</label>
            <input value={cd.registration_number} disabled={!p.editable} className={inputCls}
                   data-testid="kyb-company-regnumber-input"
                   onChange={(e) => { setCd({ ...cd, registration_number: e.target.value }); mark(); }} /></div>
          <div><label className={labelCls}>Fecha de inscripción</label>
            <input type="date" value={cd.registration_date} disabled={!p.editable} className={inputCls}
                   data-testid="kyb-company-regdate-input"
                   onChange={(e) => { setCd({ ...cd, registration_date: e.target.value }); mark(); }} /></div>
          <div><label className={labelCls}>Página web</label>
            <input value={cd.website} disabled={!p.editable} className={inputCls}
                   placeholder="https://…" data-testid="kyb-company-website-input"
                   onChange={(e) => { setCd({ ...cd, website: e.target.value }); mark(); }} />
            <p className="text-xs text-fg-muted mt-1">Si tu empresa no tiene sitio web,
              se acepta el LinkedIn de la empresa o del representante legal.</p></div>
          <button className={buttonCls} disabled={!p.editable}
                  data-testid="kyb-company-data-save"
                  onClick={() => put("data", cd, "Datos de la empresa")}>Guardar</button>
        </div>
      </Card>
      <Card title="Sede social">
        <Chk on={"address" in saved} />
        <div className="space-y-4">
          <div><label className={labelCls}>Dirección</label>
            <input value={ad.raw} disabled={!p.editable} className={inputCls}
                   placeholder="Calle, número, localidad" list="kyb-addr-hints"
                   data-testid="kyb-company-address-input"
                   onChange={(e) => { setAd({ ...ad, raw: e.target.value }); mark(); }} />
            <datalist id="kyb-addr-hints">
              {ad.raw.length > 3 && <option value={`${ad.raw}, CABA, Argentina`} />}
            </datalist></div>
          <div className="grid grid-cols-2 gap-3">
            {[["street", "Calle"], ["number", "Número"], ["city", "Localidad"],
              ["state", "Provincia"], ["postal_code", "Código postal"], ["country", "País (ISO-2)"]]
              .map(([k, lbl]) => (
              <div key={k}><label className={labelCls}>{lbl}</label>
                <input value={(ad as any)[k] || ""} disabled={!p.editable} className={inputCls}
                       data-testid={`kyb-company-address-${k}-input`}
                       onChange={(e) => { setAd({ ...ad, [k]: e.target.value }); mark(); }} /></div>))}
          </div>
          <button className={buttonCls} disabled={!p.editable}
                  data-testid="kyb-company-address-save"
                  onClick={() => put("address", ad, "Sede social")}>Guardar</button>
        </div>
      </Card>
      <Card title="Operatoria">
        <Chk on={"operations" in saved} />
        <div className="space-y-4">
          <div><label className={labelCls}>Monto mensual estimado (USD)</label>
            <input type="number" min={0} value={op.estimated_monthly_volume_usd}
                   disabled={!p.editable} className={inputCls}
                   data-testid="kyb-ops-volume-input"
                   onChange={(e) => { setOp({ ...op, estimated_monthly_volume_usd: e.target.value }); mark(); }} />
            <p className="text-xs text-fg-muted mt-1">Estimá el volumen mensual que
              planeás operar en la plataforma. Es una referencia declarativa.</p></div>
          <div><label className={labelCls}>Objetivo</label>
            {purposesList.map(([v, lbl]) => (
              <label key={v} className="flex items-center gap-2 text-sm text-fg py-1">
                <input type="checkbox" checked={op.purposes.includes(v)} disabled={!p.editable}
                       data-testid={`kyb-ops-purpose-${v}`}
                       onChange={(e) => { setOp({ ...op, purposes: e.target.checked
                         ? [...op.purposes, v] : op.purposes.filter((x: string) => x !== v) }); mark(); }} />
                {lbl}</label>))}
            {op.purposes.includes("OTHER") && (
              <input placeholder="Detallá el objetivo" value={op.purpose_other} className={inputCls}
                     data-testid="kyb-ops-purpose-other-input"
                     onChange={(e) => { setOp({ ...op, purpose_other: e.target.value }); mark(); }} />)}
          </div>
          <div><label className={labelCls}>Fondo/s a suscribir</label>
            {[["PROSPER_ARS", "PROSPER ARS"], ["PROSPER_USD", "PROSPER USD"]].map(([v, lbl]) => (
              <label key={v} className="flex items-center gap-2 text-sm text-fg py-1">
                <input type="checkbox" checked={op.funds_subscribed.includes(v)} disabled={!p.editable}
                       data-testid={`kyb-ops-fund-${v}`}
                       onChange={(e) => { setOp({ ...op, funds_subscribed: e.target.checked
                         ? [...op.funds_subscribed, v] : op.funds_subscribed.filter((x: string) => x !== v) }); mark(); }} />
                {lbl}</label>))}</div>
          <button className={buttonCls} disabled={!p.editable}
                  data-testid="kyb-ops-save"
                  onClick={() => put("operations", { ...op,
                    estimated_monthly_volume_usd: op.estimated_monthly_volume_usd === ""
                      ? null : Number(op.estimated_monthly_volume_usd) }, "Operatoria")}>Guardar</button>
        </div>
      </Card>
      <Card title="Origen de fondos">
        <Chk on={"funds_origin" in saved} />
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
          {[["OWN_TREASURY", "Fondos propios de tesorería"],
            ["CLIENT_FUNDS", "Fondos de clientes bajo custodia"],
            ["MIXED", "Esquema mixto"]].map(([v, lbl]) => (
            <button key={v} disabled={!p.editable}
                    data-testid={`kyb-fo-card-${v}`}
                    onClick={() => { setFo({ ...fo, type: v }); mark(); }}
                    className={`rounded-xl border p-4 text-sm text-left transition-colors ${
                      fo.type === v ? "border-primary bg-primary/10 text-primary font-medium"
                                    : "border-border bg-bg text-fg hover:border-primary/50"}`}>
              {lbl}</button>))}
        </div>
        {showClientBlock && (
          <div className="space-y-3 rounded-lg border border-border bg-bg p-4 mb-4"
               data-testid="kyb-fo-client-block">
            {fo.type === "MIXED" && (
              <div><label className={labelCls}>Proporción estimada de fondos de clientes (%)</label>
                <input type="number" min={0} max={100} value={fo.client_funds_ratio}
                       className={inputCls} data-testid="kyb-fo-ratio-input"
                       onChange={(e) => { setFo({ ...fo, client_funds_ratio: e.target.value }); mark(); }} /></div>)}
            <div className="grid grid-cols-2 gap-3">
              <div><label className={labelCls}>Tipo de licencia / registro</label>
                <input value={fo.license_type} className={inputCls}
                       data-testid="kyb-fo-license-type-input"
                       onChange={(e) => { setFo({ ...fo, license_type: e.target.value }); mark(); }} /></div>
              <div><label className={labelCls}>Número</label>
                <input value={fo.license_number} className={inputCls}
                       data-testid="kyb-fo-license-number-input"
                       onChange={(e) => { setFo({ ...fo, license_number: e.target.value }); mark(); }} /></div>
            </div>
            <label className="flex items-center gap-2 text-sm text-fg">
              <input type="checkbox" checked={!!fo.has_aml_policy}
                     data-testid="kyb-fo-aml-checkbox"
                     onChange={(e) => { setFo({ ...fo, has_aml_policy: e.target.checked }); mark(); }} />
              La empresa cuenta con política PLA/FT propia</label>
            <div><label className={labelCls}>Oficial de cumplimiento</label>
              <input value={fo.compliance_officer_name} className={inputCls}
                     data-testid="kyb-fo-officer-input"
                     onChange={(e) => { setFo({ ...fo, compliance_officer_name: e.target.value }); mark(); }} /></div>
            <div><label className={labelCls}>Proceso de KYC aplicado a usuarios finales</label>
              <textarea rows={3} value={fo.end_user_kyc_description} className={inputCls}
                        data-testid="kyb-fo-kyc-textarea"
                        onChange={(e) => { setFo({ ...fo, end_user_kyc_description: e.target.value }); mark(); }} /></div>
            <label className="flex items-center gap-2 text-sm text-fg">
              <input type="checkbox" checked={!!fo.segregated_assets}
                     data-testid="kyb-fo-segregation-checkbox"
                     onChange={(e) => { setFo({ ...fo, segregated_assets: e.target.checked }); mark(); }} />
              Declaro segregación patrimonial de los fondos de clientes</label>
          </div>)}
        <div className="space-y-3 mb-4">
          <label className="flex items-center gap-2 text-sm text-fg">
            <input type="checkbox" checked={!!fo.is_uif_obliged_subject} disabled={!p.editable}
                   data-testid="kyb-fo-uif-checkbox"
                   onChange={(e) => { setFo({ ...fo, is_uif_obliged_subject: e.target.checked }); mark(); }} />
            La empresa es sujeto obligado ante la UIF</label>
          {fo.is_uif_obliged_subject && (
            <input placeholder="Número de registración UIF" value={fo.uif_registration_number}
                   className={inputCls} data-testid="kyb-fo-uif-number-input"
                   onChange={(e) => { setFo({ ...fo, uif_registration_number: e.target.value }); mark(); }} />)}
        </div>
        <button className={buttonCls} disabled={!p.editable || !fo.type}
                data-testid="kyb-fo-save"
                onClick={() => put("funds-origin", { ...fo,
                  client_funds_ratio: fo.client_funds_ratio === "" ? null : Number(fo.client_funds_ratio),
                  tax_residences: prof.tax_residences || [] }, "Origen de fondos")}>Guardar</button>
      </Card>
    </div>
  );
}

function DocsSection(p: P) {
  const slots = p.data.case.sections?.documentation?.slots || {};
  return (
    <div>
      <Observation data={p.data} section="documentation" />
      {p.data.phase3_slots.map((slot) => (
        <DocSlot key={slot} slot={slot} p={p} confirmed={slots[slot] === "confirmed"} />))}
      <UboSection data={p.data} reload={p.reload} editable={p.editable} />
    </div>
  );
}

function DocSlot({ slot, p, confirmed }: { slot: string; p: P; confirmed: boolean }) {
  const meta = SLOT_META[slot];
  const docs = p.data.documents.filter((d) => d.slot === slot && d.is_current);
  const [desc, setDesc] = useState("");
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  async function upload(file: File) {
    setBusy(true);
    const fd = new FormData();
    fd.append("slot", slot); fd.append("description", desc); fd.append("file", file);
    try { await api("/v1/kyb/case/documents", { method: "POST", body: fd });
      toast.success("Archivo cargado"); await p.reload(); }
    catch (e: any) { toast.error(e?.message || "Error al subir el archivo"); }
    finally { setBusy(false); }
  }
  async function confirm(recently = false) {
    try { await api("/v1/kyb/case/documents/confirm", { method: "POST",
      body: JSON.stringify({ slot, recently_incorporated: recently }) });
      toast.success("Subsección confirmada"); await p.reload(); }
    catch (e: any) { toast.error(e?.message || "No se pudo confirmar"); }
  }
  async function remove(id: string) {
    try { await api(`/v1/kyb/case/documents/${id}`, { method: "DELETE" });
      await p.reload(); } catch (e: any) { toast.error(e?.message); }
  }
  return (
    <Card title={meta.title + (confirmed ? " ✓" : "")}>
      <p className="text-sm text-fg-muted mb-3">{meta.text}</p>
      <textarea rows={2} maxLength={499} value={desc} disabled={!p.editable}
                placeholder="Descripción (opcional)" className={inputCls}
                data-testid={`kyb-doc-desc-${slot}`}
                onChange={(e) => setDesc(e.target.value)} />
      <p className="text-xs text-fg-muted mt-1 mb-3">{desc.length}/499</p>
      <div className="rounded-xl border-2 border-dashed border-border p-6 text-center cursor-pointer hover:border-primary/60 transition-colors"
           data-testid={`kyb-doc-dropzone-${slot}`}
           onClick={() => p.editable && inputRef.current?.click()}
           onDragOver={(e) => e.preventDefault()}
           onDrop={(e) => { e.preventDefault();
             if (p.editable && e.dataTransfer.files[0]) upload(e.dataTransfer.files[0]); }}>
        <UploadCloud size={22} className="mx-auto text-fg-muted mb-2" />
        <p className="text-sm text-fg">{busy ? "Subiendo…" : "Arrastra tu archivo aquí"}</p>
        <p className="text-xs text-primary mt-1">Seleccionar archivo</p>
        <input ref={inputRef} type="file" className="hidden"
               data-testid={`kyb-doc-file-${slot}`}
               onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
      </div>
      {docs.length > 0 && (
        <div className="mt-4">
          <p className="text-xs uppercase tracking-wide text-fg-muted mb-2">Archivos cargados</p>
          {docs.map((d) => (
            <div key={d.document_id} className="flex items-center gap-2 text-sm text-fg py-1.5 border-b border-border last:border-0"
                 data-testid={`kyb-doc-row-${d.document_id}`}>
              <FileText size={14} className="text-fg-muted" />
              <span className="flex-1 truncate">{d.filename} <span className="text-fg-muted">v{d.version}</span></span>
              {p.editable && (
                <button onClick={() => remove(d.document_id)}
                        data-testid={`kyb-doc-delete-${d.document_id}`}
                        className="text-danger hover:bg-danger/10 rounded p-1"><Trash2 size={14} /></button>)}
            </div>))}
        </div>)}
      <div className="flex gap-3 mt-4">
        <button className={buttonCls} disabled={!p.editable || confirmed || docs.length === 0}
                data-testid={`kyb-doc-confirm-${slot}`}
                onClick={() => confirm(false)}>Confirmar</button>
        {slot === "funds_origin_evidence" && !confirmed && (
          <button className="flex-1 rounded-lg border border-border py-2.5 text-sm text-fg hover:bg-bg disabled:opacity-50"
                  disabled={!p.editable}
                  data-testid="kyb-doc-recently-incorporated-button"
                  onClick={() => confirm(true)}>La empresa es de reciente creación</button>)}
      </div>
    </Card>
  );
}


/* --------------------------- Fase 8 — Equipo ---------------------------- */
type TeamData = {
  case_id: string; legal_representative: any; invitations: any[];
  members: any[]; banner: string;
};

function TeamSection({ editable }: P) {
  const [data, setData] = useState<TeamData | null>(null);
  const [form, setForm] = useState({ email: "", tax_id: "",
    intended_role: "read_only" as "administrator" | "operator" | "read_only",
    full_name: "" });
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try { setData(await api<TeamData>("/v1/kyb/case/team")); }
    catch (e: any) { toast.error(e?.message); }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function invite() {
    setBusy(true);
    try {
      await api("/v1/kyb/case/team", { method: "POST",
        body: JSON.stringify({ ...form, country_of_residence: "AR" }) });
      toast.success("Invitación enviada");
      setForm({ email: "", tax_id: "", intended_role: "read_only",
                full_name: "" });
      await load();
    } catch (e: any) { toast.error(e?.message); }
    finally { setBusy(false); }
  }
  async function revoke(id: string) {
    setBusy(true);
    try {
      await api(`/v1/kyb/case/team/${id}`, { method: "DELETE" });
      await load(); toast.success("Invitación revocada");
    } catch (e: any) { toast.error(e?.message); }
    finally { setBusy(false); }
  }

  if (!data) return <Card title="Gestioná tu equipo (opcional)"><p className="text-sm text-fg-muted">Cargando…</p></Card>;
  const rep = data.legal_representative || {};
  const activeInvites = data.invitations.filter(
    (i: any) => i.status === "pending");
  const roleCards = [
    { key: "administrator", label: "ADMINISTRADOR",
      desc: "Puede ver y operar, pero no gestionar miembros." },
    { key: "operator", label: "OPERADOR",
      desc: "Puede ver información y crear envíos de dinero (esta capacidad está en implementación — hoy opera como miembro solo lectura)." },
    { key: "read_only", label: "SÓLO LECTURA",
      desc: "Solo puede ver información, no puede operar." },
  ];

  return (
    <Card title="Gestioná tu equipo (opcional)">
      <p className="text-sm text-fg-muted mb-4" data-testid="kyb-team-banner">
        {data.banner}
      </p>
      <div className="bg-bg rounded-xl border border-border p-3 mb-4"
           data-testid="kyb-team-legal-rep">
        <p className="text-xs text-fg-muted uppercase tracking-wide">Representante legal · Administrador</p>
        <p className="text-sm text-fg mt-1">
          {rep.full_name || "—"}{" "}
          {rep.email && <span className="text-fg-muted">· {rep.email}</span>}
        </p>
      </div>
      <p className="text-xs font-medium text-fg mb-2">Otros miembros</p>
      <div className="space-y-1 mb-3" data-testid="kyb-team-members">
        {data.members.filter((m: any) => m.email !== rep.email).length === 0
          && activeInvites.length === 0 && (
            <p className="text-xs text-fg-muted">Todavía no hay miembros
              adicionales.</p>)}
        {data.members.filter((m: any) => m.email !== rep.email).map((m: any) => (
          <div key={m.user_id} className="flex justify-between text-xs border border-border rounded px-2 py-1"
               data-testid={`kyb-team-member-${m.user_id}`}>
            <span>{m.email} <span className="text-fg-muted">·
              {m.intended_role || m.role}</span></span>
            <span className="text-success">activo</span>
          </div>))}
        {activeInvites.map((i: any) => (
          <div key={i.invitation_id} className="flex justify-between text-xs border border-border rounded px-2 py-1"
               data-testid={`kyb-team-invitation-${i.invitation_id}`}>
            <span>{i.email} <span className="text-fg-muted">·
              {i.intended_role}</span></span>
            <button className="text-danger hover:underline"
                    disabled={!editable || busy} onClick={() => revoke(i.invitation_id)}
                    data-testid={`kyb-team-revoke-${i.invitation_id}`}>
              Revocar</button>
          </div>))}
      </div>
      {editable && (
        <details className="border border-border rounded-xl p-3"
                 data-testid="kyb-team-invite-details">
          <summary className="cursor-pointer text-sm text-primary font-medium">
            Invitar miembro</summary>
          <div className="mt-3 space-y-3">
            <div>
              <label className="text-xs text-fg-muted">País de residencia</label>
              <input className="mt-1 w-full rounded border border-border bg-bg px-2 py-1.5 text-sm"
                     value="Argentina" disabled
                     data-testid="kyb-team-invite-country" />
              <p className="text-[11px] text-fg-muted mt-0.5">En esta fase
                solo se pueden invitar residentes fiscales de Argentina.</p>
            </div>
            <div>
              <label className="text-xs text-fg-muted">CUIT/CUIL</label>
              <input className="mt-1 w-full rounded border border-border bg-bg px-2 py-1.5 text-sm font-mono"
                     value={form.tax_id}
                     data-testid="kyb-team-invite-tax-id"
                     onChange={(e) => setForm({ ...form,
                       tax_id: e.target.value.replace(/\D/g, "").slice(0, 11) })} />
              <p className="text-[11px] text-fg-muted mt-0.5">Al aceptar la
                invitación se valida que este CUIT coincida con el del
                usuario que la acepta.</p>
            </div>
            <div>
              <label className="text-xs text-fg-muted">Correo electrónico</label>
              <input className="mt-1 w-full rounded border border-border bg-bg px-2 py-1.5 text-sm"
                     type="email" value={form.email}
                     data-testid="kyb-team-invite-email"
                     onChange={(e) => setForm({ ...form, email: e.target.value })} />
            </div>
            <div>
              <p className="text-xs text-fg-muted mb-1">Rol</p>
              <div className="grid gap-2 md:grid-cols-3">
                {roleCards.map((r) => (
                  <button key={r.key} type="button"
                          onClick={() => setForm({ ...form, intended_role: r.key as any })}
                          data-testid={`kyb-team-invite-role-${r.key}`}
                          className={`text-left rounded-lg border p-2 text-xs ${
                            form.intended_role === r.key
                              ? "border-primary bg-primary/10"
                              : "border-border bg-bg"}`}>
                    <p className="font-medium text-fg text-[11px]">{r.label}</p>
                    <p className="text-fg-muted mt-1">{r.desc}</p>
                  </button>))}
              </div>
            </div>
            <button className="rounded-lg bg-primary text-white px-3 py-1.5 text-sm disabled:opacity-40"
                    disabled={busy || form.tax_id.length !== 11 || !form.email}
                    onClick={invite}
                    data-testid="kyb-team-invite-submit">Enviar invitación</button>
          </div>
        </details>)}
    </Card>
  );
}
