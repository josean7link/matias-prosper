"use client";
/* Fase 8 — Página pública para cargar documentación por enlace. */
import { notFound, useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Upload, FileText } from "lucide-react";
import { toast } from "sonner";
import { kybEnabled } from "@/app/kyb/_components/KybShell";

const SLOT_LABELS: Record<string, string> = {
  tax_registration_certificate: "Certificado de inscripción tributaria",
  constitutive_document: "Estatuto/instrumento constitutivo",
  funds_origin_evidence: "Evidencia de origen de fondos",
  authorities_appointment: "Designación de autoridades",
  company_proof_of_address: "Comprobante de domicilio",
  ubo_document_front: "Documento del beneficiario — frente",
  ubo_document_back: "Documento del beneficiario — dorso",
};

async function apiPublic(path: string, init: RequestInit = {}) {
  const base = process.env.NEXT_PUBLIC_BACKEND_URL || "";
  const r = await fetch(`${base}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init.headers || {}) },
  });
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try { const j = await r.json(); msg = j?.detail || msg; } catch {}
    throw new Error(msg);
  }
  return r.json();
}

export default function SharedUploadPage() {
  if (!kybEnabled()) notFound();
  const params = useParams<{ token: string }>();
  const token = params?.token as string;
  const [ctx, setCtx] = useState<any>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");
  const load = useCallback(async () => {
    try { setCtx(await apiPublic(`/api/v1/kyb/shared/${token}`)); setErr(""); }
    catch (e: any) { setErr(e?.message || "Enlace inválido"); }
  }, [token]);
  useEffect(() => { load(); }, [load]);

  async function upload(slot: string, file: File) {
    setBusy(slot);
    try {
      const fd = new FormData(); fd.append("slot", slot); fd.append("file", file);
      const base = process.env.NEXT_PUBLIC_BACKEND_URL || "";
      const r = await fetch(`${base}/api/v1/kyb/shared/${token}/documents`,
        { method: "POST", body: fd });
      if (!r.ok) throw new Error((await r.json())?.detail || `HTTP ${r.status}`);
      toast.success(`Archivo cargado: ${SLOT_LABELS[slot] || slot}`);
      await load();
    } catch (e: any) { toast.error(e?.message); }
    finally { setBusy(""); }
  }
  async function confirmSlot(slot: string) {
    setBusy(slot);
    try {
      await apiPublic(`/api/v1/kyb/shared/${token}/documents/confirm`,
        { method: "POST", body: JSON.stringify({ slot }) });
      toast.success("Sección confirmada");
      await load();
    } catch (e: any) { toast.error(e?.message); }
    finally { setBusy(""); }
  }

  if (err) return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <div className="max-w-md text-center" data-testid="kyb-shared-error">
        <h1 className="text-xl font-semibold text-fg">Enlace inválido</h1>
        <p className="mt-2 text-sm text-fg-muted">{err}</p>
        <p className="mt-1 text-xs text-fg-muted">Si te llegó este enlace,
          pedile al administrador de la empresa que genere uno nuevo.</p>
      </div>
    </div>);
  if (!ctx) return <p className="p-6 text-sm text-fg-muted">Cargando…</p>;

  return (
    <div className="min-h-screen bg-bg" data-testid="kyb-shared-page">
      <header className="bg-surface border-b border-border py-4 px-6">
        <h1 className="text-lg font-semibold text-fg">
          Documentación de {ctx.company_name}</h1>
        <p className="text-xs text-fg-muted">
          Enlace de acceso · vence {ctx.expires_at?.slice(0, 19)}. Los archivos
          que subas quedan registrados como &ldquo;cargados por
          tercero&rdquo;. No se te pide identificación ni permisos de la
          empresa.
        </p>
      </header>
      <main className="max-w-3xl mx-auto p-6 space-y-4">
        <section>
          <h2 className="text-sm font-medium text-fg mb-2">
            Documentación societaria</h2>
          <div className="grid gap-3">
            {ctx.phase3_slots.map((slot: string) =>
              <SlotCard key={slot} slot={slot}
                        docs={ctx.documents_uploaded_here.filter(
                          (d: any) => d.slot === slot)}
                        onUpload={(f: File) => upload(slot, f)}
                        onConfirm={() => confirmSlot(slot)}
                        busy={busy === slot} />)}
          </div>
        </section>
        <section>
          <h2 className="text-sm font-medium text-fg mb-2 mt-4">
            Documentación de beneficiarios</h2>
          <div className="grid gap-3">
            {ctx.ubo_slots.map((slot: string) =>
              <SlotCard key={slot} slot={slot}
                        docs={ctx.documents_uploaded_here.filter(
                          (d: any) => d.slot === slot)}
                        onUpload={(f: File) => upload(slot, f)}
                        onConfirm={null}
                        busy={busy === slot} />)}
          </div>
        </section>
        <p className="text-xs text-fg-muted mt-6">
          Cuando termines, avisale al titular. El envío del expediente a
          revisión lo hace el administrador de la empresa desde su
          sesión — no se puede disparar desde este enlace.
        </p>
      </main>
    </div>
  );
}

function SlotCard({ slot, docs, onUpload, onConfirm, busy }: {
  slot: string; docs: any[]; onUpload: (f: File) => void;
  onConfirm: (() => void) | null; busy: boolean;
}) {
  const ref = useRef<HTMLInputElement>(null);
  return (
    <div className="border border-border rounded-xl p-3 bg-surface"
         data-testid={`kyb-shared-slot-${slot}`}>
      <div className="flex items-center justify-between">
        <p className="text-sm text-fg">{SLOT_LABELS[slot] || slot}</p>
        {docs.length > 0 && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-success/15 text-success">
            {docs.length} archivo{docs.length > 1 ? "s" : ""}</span>)}
      </div>
      {docs.length > 0 && (
        <ul className="mt-1 text-xs text-fg-muted space-y-0.5"
            data-testid={`kyb-shared-slot-docs-${slot}`}>
          {docs.slice(0, 3).map((d: any) => (
            <li key={d.document_id} className="flex items-center gap-1">
              <FileText size={11} /> {d.filename}
            </li>))}
        </ul>)}
      <div className="mt-2 flex gap-2">
        <input ref={ref} type="file" className="hidden"
               data-testid={`kyb-shared-file-${slot}`}
               onChange={(e) => {
                 const f = e.target.files?.[0]; if (f) onUpload(f);
                 if (ref.current) ref.current.value = ""; }} />
        <button className="rounded border border-border px-2 py-1 text-xs disabled:opacity-40"
                disabled={busy} onClick={() => ref.current?.click()}
                data-testid={`kyb-shared-upload-${slot}`}>
          <Upload size={11} className="inline mr-1" /> Cargar archivo</button>
        {onConfirm && docs.length > 0 && (
          <button className="rounded border border-border px-2 py-1 text-xs disabled:opacity-40"
                  disabled={busy} onClick={onConfirm}
                  data-testid={`kyb-shared-confirm-${slot}`}>
            Confirmar sección</button>)}
      </div>
    </div>
  );
}
