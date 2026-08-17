"use client";
/* Fase 3 — Wizard del expediente KYB. Guardado por sección (no lineal),
   autosave 20s, modal de cambios sin guardar, read-only por estado. */
import { notFound, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle2, Circle, CircleAlert, LogOut, Link2, LifeBuoy,
         BookOpen, Lock } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { KybShell, buttonCls, kybEnabled } from "../_components/KybShell";
import { SECTIONS_META, SectionBody } from "./sections";

export type CaseData = {
  case: any; profile: any; documents: any[]; ubos: any[]; legal_docs: any[];
  progress: { sections: Record<string, string>; missing: string[];
              submit_blockers: { code: string; section: string;
                                 description: string }[];
              can_submit: boolean };
  editable: boolean; editable_sections: string[]; phase3_slots: string[];
  ubo_slots: string[];
};

export default function KybOnboardingPage() {
  if (!kybEnabled()) notFound();
  const router = useRouter();
  const [data, setData] = useState<CaseData | null>(null);
  const [err, setErr] = useState("");
  const [active, setActive] = useState("tax_identification");
  const [dirty, setDirty] = useState(false);
  const [leaveTo, setLeaveTo] = useState<null | (() => void)>(null);
  const [shareOpen, setShareOpen] = useState(false);
  const autosaves = useRef<Record<string, () => Promise<void>>>({});

  const reload = useCallback(async () => {
    try { setData(await api<CaseData>("/v1/kyb/case")); setErr(""); }
    catch (e: any) { setErr(e?.message || "No pudimos cargar tu expediente"); }
  }, []);
  useEffect(() => { reload(); }, [reload]);

  // Autosave de borrador cada 20 s sobre campos modificados.
  useEffect(() => {
    const t = setInterval(async () => {
      if (!dirty) return;
      for (const fn of Object.values(autosaves.current)) {
        try { await fn(); } catch { /* draft best-effort */ }
      }
    }, 20000);
    return () => clearInterval(t);
  }, [dirty]);

  // Modal del navegador al salir con cambios pendientes.
  useEffect(() => {
    const h = (e: BeforeUnloadEvent) => {
      if (dirty) { e.preventDefault(); e.returnValue = ""; }
    };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [dirty]);

  const guardNav = (fn: () => void) => (dirty ? setLeaveTo(() => fn) : fn());

  async function logout() {
    try { await api("/v1/auth/logout", { method: "POST" }); } catch {}
    router.push("/access");
  }

  async function submitCase() {
    try {
      await api("/v1/kyb/case/submit", { method: "POST" });
      toast.success("Expediente enviado a revisión");
      await reload();
    } catch (e: any) { toast.error(e?.message || "No se pudo enviar"); }
  }

  if (err) {
    return (
      <KybShell>
        <div className="bg-surface border border-border rounded-2xl p-8 text-center"
             data-testid="kyb-onboarding-error">
          <p className="text-sm text-fg-muted">{err}</p>
        </div>
      </KybShell>
    );
  }
  if (!data) {
    return <KybShell><p className="text-center text-fg-muted text-sm"
                        data-testid="kyb-onboarding-loading">Cargando…</p></KybShell>;
  }

  const sections = data.progress.sections;
  const caseStatus = data.case.status;
  const sectionEditable = (k: string) =>
    data.editable && (caseStatus !== "info_required"
      || data.editable_sections.includes(k));

  return (
    <div className="min-h-screen bg-bg flex flex-col" data-testid="kyb-onboarding-page">
      {/* Cabecera */}
      <header className="border-b border-border bg-surface sticky top-0 z-20">
        <div className="max-w-6xl mx-auto px-6 py-3 flex items-center justify-between gap-4">
          <h1 className="text-lg font-semibold text-fg">Creación de cuenta empresa</h1>
          <div className="flex items-center gap-1.5 text-xs">
            {/* F8-fix (post-diag 6 puntos): botón Tutorial oculto hasta
                que exista contenido real. Preferimos no anunciar un
                feature futuro. */}
            <button className="px-2.5 py-1.5 rounded-lg text-fg-muted hover:bg-bg flex items-center gap-1"
                    data-testid="kyb-header-advisor-link"
                    onClick={() => toast.info("Un asesor se va a contactar a tu email registrado")}>
              <LifeBuoy size={14} /> Contactar con asesor
            </button>
            <button className="px-2.5 py-1.5 rounded-lg text-fg-muted hover:bg-bg flex items-center gap-1"
                    data-testid="kyb-header-share-link"
                    onClick={() => setShareOpen(true)}>
              <Link2 size={14} /> Compartir link de acceso
            </button>
            <button className="px-2.5 py-1.5 rounded-lg text-danger hover:bg-danger/10 flex items-center gap-1"
                    data-testid="kyb-header-logout-button"
                    onClick={() => guardNav(logout)}>
              <LogOut size={14} /> Cerrar sesión
            </button>
          </div>
        </div>
      </header>

      {/* Banner read-only */}
      {!data.editable && (
        <div className="bg-warning/10 border-b border-warning/30 text-center py-2 px-4 text-sm text-fg"
             data-testid="kyb-readonly-banner">
          Tu expediente está <strong>{caseStatus === "approved" ? "aprobado" : "en revisión"}</strong> y
          no puede editarse en este momento. Te avisaremos por email ante cualquier novedad.
        </div>
      )}
      {caseStatus === "info_required" && (
        <div className="bg-warning/10 border-b border-warning/30 text-center py-2 px-4 text-sm text-fg"
             data-testid="kyb-info-required-banner">
          El analista solicitó correcciones: solo podés editar las secciones marcadas con observaciones.
        </div>
      )}

      <div className="flex-1 max-w-6xl mx-auto w-full px-6 py-8 grid grid-cols-1 md:grid-cols-[300px_1fr] gap-8">
        {/* Columna izquierda */}
        <aside className="md:sticky md:top-20 self-start" data-testid="kyb-nav-panel">
          <p className="text-xs uppercase tracking-wide text-fg-muted mb-3">Información requerida</p>
          <nav className="space-y-1">
            {SECTIONS_META.map((s) => {
              const st = sections[s.key];
              const observed = st === "observed";
              return (
                <button key={s.key}
                        data-testid={`kyb-nav-${s.key}`}
                        onClick={() => guardNav(() => setActive(s.key))}
                        className={`w-full text-left px-3 py-2.5 rounded-lg text-sm flex items-center gap-2 transition-colors ${
                          active === s.key ? "bg-primary/10 text-primary font-medium"
                                           : "text-fg hover:bg-surface"}`}>
                  {st === "completed"
                    ? <CheckCircle2 size={16} className="text-success shrink-0" />
                    : st === "resubmitted"
                      ? <CheckCircle2 size={16} className="text-warning shrink-0" />
                      : observed
                        ? <CircleAlert size={16} className="text-warning shrink-0" />
                        : <Circle size={16} className="text-fg-muted shrink-0" />}
                  <span className="flex-1">{s.label}</span>
                  {s.key === "tax_identification" && data.profile.tax_id_locked
                    && <Lock size={12} className="text-fg-muted" />}
                </button>
              );
            })}
          </nav>
          {/* Botón fijo Enviar a revisión */}
          <div className="mt-6 sticky bottom-4">
            <div className="group relative">
              <button disabled={!data.progress.can_submit}
                      className={buttonCls +
                        (data.progress.can_submit ? "" : " !cursor-not-allowed")}
                      data-testid="kyb-submit-review-button"
                      onClick={() => data.progress.can_submit &&
                        guardNav(submitCase)}>
                Enviar a revisión
              </button>
              {!data.progress.can_submit && (
                <div className="absolute bottom-full mb-2 left-0 right-0 hidden group-hover:block bg-fg text-bg text-xs rounded-lg p-3 shadow-lg z-30"
                     data-testid="kyb-submit-tooltip">
                  {data.progress.submit_blockers?.length
                    ? (<><p className="font-medium mb-1">Falta completar:</p>
                        <ul className="list-disc pl-4 space-y-0.5">
                          {data.progress.submit_blockers.map((b, i) =>
                            <li key={i}>{b.description}</li>)}
                        </ul></>)
                    : "Tu expediente ya fue enviado a revisión."}
                </div>)}
            </div>
          </div>
        </aside>

        {/* Columna derecha */}
        <main className="min-w-0">
          <SectionBody
            active={active} data={data} reload={reload}
            editable={sectionEditable(active)}
            setDirty={setDirty}
            registerAutosave={(k, fn) => { autosaves.current[k] = fn; }} />
        </main>
      </div>

      {/* Modal de cambios sin guardar */}
      {leaveTo && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
             data-testid="kyb-unsaved-modal">
          <div className="bg-surface border border-border rounded-2xl p-6 max-w-sm w-full">
            <h2 className="text-lg font-semibold text-fg mb-2">¿Estás seguro?</h2>
            <p className="text-sm text-fg-muted mb-6">
              Si decides salir de esta página, las modificaciones que no hayas
              guardado se perderán.
            </p>
            <div className="flex gap-3">
              <button className="flex-1 rounded-lg border border-border py-2.5 text-sm text-fg hover:bg-bg"
                      data-testid="kyb-unsaved-cancel-button"
                      onClick={() => setLeaveTo(null)}>Cancelar</button>
              <button className="flex-1 rounded-lg bg-danger text-white py-2.5 text-sm hover:opacity-90"
                      data-testid="kyb-unsaved-leave-button"
                      onClick={() => { const fn = leaveTo; setLeaveTo(null);
                                       setDirty(false); fn(); }}>Salir</button>
            </div>
          </div>
        </div>
      )}

      {shareOpen && <ShareLinkModal onClose={() => setShareOpen(false)} />}
    </div>
  );
}

/* -------------------------- Fase 8 — Compartir --------------------------- */
function ShareLinkModal({ onClose }: { onClose: () => void }) {
  const [items, setItems] = useState<any[]>([]);
  const [hours, setHours] = useState(168);
  const [busy, setBusy] = useState(false);
  const [issued, setIssued] = useState<{ url: string; expires_at: string } | null>(null);
  const load = useCallback(async () => {
    try { const r: any = await api("/v1/kyb/case/shared-links");
          setItems(r.items || []); }
    catch (e: any) { toast.error(e?.message); }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function create() {
    setBusy(true);
    try {
      const r: any = await api("/v1/kyb/case/shared-links", { method: "POST",
        body: JSON.stringify({ expires_in_hours: hours }) });
      setIssued({ url: r.url, expires_at: r.expires_at });
      await load();
    } catch (e: any) { toast.error(e?.message); }
    finally { setBusy(false); }
  }
  async function revoke(id: string) {
    setBusy(true);
    try {
      await api(`/v1/kyb/case/shared-links/${id}`, { method: "DELETE" });
      await load(); toast.success("Enlace revocado");
    } catch (e: any) { toast.error(e?.message); }
    finally { setBusy(false); }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
         data-testid="kyb-share-modal">
      <div className="bg-surface border border-border rounded-2xl p-5 max-w-lg w-full max-h-[90vh] overflow-y-auto">
        <h2 className="text-lg font-semibold text-fg mb-1">
          Compartir enlace de acceso</h2>
        <p className="text-sm text-fg-muted mb-3">
          El enlace deja cargar solo <strong>documentación societaria y de
          beneficiarios</strong>. No da acceso a CUIT, equipo ni al envío
          a revisión. Todo lo que carguen queda registrado como
          &ldquo;subido por tercero&rdquo;.
        </p>
        {issued ? (
          <div className="rounded-lg border border-primary/50 bg-primary/5 p-3 text-sm mb-3"
               data-testid="kyb-share-issued">
            <p className="font-medium text-fg">Enlace creado</p>
            <p className="mt-1 text-xs text-fg-muted">Se muestra una sola
              vez. Copialo y compartilo por un canal seguro.</p>
            <div className="mt-2 flex gap-2">
              <input readOnly className="flex-1 rounded border border-border bg-bg px-2 py-1 text-xs font-mono"
                     value={issued.url}
                     data-testid="kyb-share-issued-url" />
              <button className="rounded border border-border px-2 py-1 text-xs"
                      onClick={() => { navigator.clipboard?.writeText(issued.url);
                                       toast.success("Copiado"); }}
                      data-testid="kyb-share-copy-button">Copiar</button>
            </div>
            <p className="mt-1 text-[11px] text-fg-muted">
              Vence el {issued.expires_at?.slice(0, 19)}
            </p>
          </div>
        ) : (
          <div className="rounded-lg border border-border p-3 mb-3">
            <label className="block text-xs text-fg-muted">Validez (horas)
              <input className="mt-1 w-24 rounded border border-border bg-bg px-2 py-1 text-sm"
                     type="number" min={1} max={720} value={hours}
                     onChange={(e) => setHours(Number(e.target.value))}
                     data-testid="kyb-share-hours-input" />
            </label>
            <button className="mt-2 rounded-lg bg-primary text-white px-3 py-1.5 text-sm disabled:opacity-40"
                    disabled={busy} onClick={create}
                    data-testid="kyb-share-create-button">
              Generar enlace</button>
          </div>
        )}
        <p className="text-xs font-medium text-fg mt-2 mb-1">Enlaces activos</p>
        <div className="space-y-1">
          {items.length === 0
            ? <p className="text-xs text-fg-muted">Sin enlaces todavía.</p>
            : items.map((it) => (
              <div key={it.link_id} className="flex items-center justify-between text-xs border border-border rounded px-2 py-1"
                   data-testid={`kyb-share-item-${it.link_id}`}>
                <div>
                  <span className={it.active ? "text-fg" : "text-fg-muted line-through"}>
                    {it.link_id}</span>
                  <span className="ml-2 text-fg-muted">vence {it.expires_at?.slice(0, 10)}</span>
                  <span className="ml-2 text-fg-muted">usos: {it.use_count || 0}</span>
                </div>
                {it.active && (
                  <button className="text-danger hover:underline"
                          disabled={busy} onClick={() => revoke(it.link_id)}
                          data-testid={`kyb-share-revoke-${it.link_id}`}>
                    Revocar</button>)}
              </div>))}
        </div>
        <div className="mt-4 flex justify-end">
          <button className="rounded border border-border px-3 py-1.5 text-sm"
                  onClick={onClose}
                  data-testid="kyb-share-close-button">Cerrar</button>
        </div>
      </div>
    </div>
  );
}
