"use client";
import Link from "next/link";
import { useSearchParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
  ArrowLeft, ArrowRight, Building2, CheckCircle2, FileUp,
  ShieldCheck, User as UserIcon, Users as UsersIcon, ClipboardCheck,
} from "lucide-react";
import { ProsperLogo } from "@/components/ProsperLogo";
import { api } from "@/lib/api";
import type { ApplyContext, ApplyPayload, UBOInput } from "@/lib/client-portal";
import { LegacyApplyForm } from "./LegacyApplyForm";

const STEPS = [
  { id: 1, label: "Bienvenida",    icon: <Building2 size={14} /> },
  { id: 2, label: "Tu identidad",  icon: <UserIcon size={14} /> },
  { id: 3, label: "Empresa",       icon: <Building2 size={14} /> },
  { id: 4, label: "UBOs",          icon: <UsersIcon size={14} /> },
  { id: 5, label: "Documentos",    icon: <FileUp size={14} /> },
  { id: 6, label: "Verificación",  icon: <ShieldCheck size={14} /> },
  { id: 7, label: "Revisar",       icon: <ClipboardCheck size={14} /> },
];

interface PersonalData {
  first_name: string; last_name: string;
  dob: string; gender: string;
  nationality: string; doc_id: string;
}

const DOC_KINDS = [
  { key: "certificate",      label: "Certificado de constitución" },
  { key: "board_resolution", label: "Board resolution / Acta" },
  { key: "address_proof",    label: "Proof of address (<3 meses)" },
  { key: "tax_id",           label: "Constancia fiscal / Tax ID" },
  { key: "financials",       label: "Estados financieros" },
];

export default function ApplyPage() {
  const params = useSearchParams();
  const router = useRouter();
  const token = params.get("token");

  const [ctx, setCtx] = useState<ApplyContext | null>(null);
  const [ctxError, setCtxError] = useState<string | null>(null);
  const [loadingCtx, setLoadingCtx] = useState(true);
  const [step, setStep] = useState(1);
  const [submitting, setSubmitting] = useState(false);

  const [personal, setPersonal] = useState<PersonalData>({
    first_name: "", last_name: "", dob: "", gender: "",
    nationality: "", doc_id: "",
  });
  const [corpLegalName, setCorpLegalName] = useState("");
  const [ubos, setUbos] = useState<UBOInput[]>([
    { full_name: "", ownership_pct: 0, nationality: "", is_pep: false },
  ]);
  const [docs, setDocs] = useState<Record<string, boolean>>({});
  const [accept, setAccept] = useState(false);

  useEffect(() => {
    if (!token) { setLoadingCtx(false); return; }
    api<ApplyContext>("/v1/apply/context", {
      method: "POST",
      body: JSON.stringify({ token }),
    })
      .then((c) => { setCtx(c); setCorpLegalName(c.legal_name || ""); })
      .catch((e: Error) => setCtxError(e.message))
      .finally(() => setLoadingCtx(false));
  }, [token]);

  // Legacy public flow (no token) — keep AiPrise integration as-is.
  if (!token) return <LegacyApplyForm />;

  if (loadingCtx) {
    return <CenterShell><p className="text-fg-subtle text-sm">Validando link…</p></CenterShell>;
  }
  if (ctxError || !ctx) {
    return (
      <CenterShell>
        <div className="prosper-card p-7 text-center max-w-md" data-testid="apply-error">
          <h1 className="font-display font-bold text-lg text-fg">Link inválido o expirado</h1>
          <p className="text-sm text-fg-muted mt-2">
            {ctxError || "Pedí un nuevo link a tu contacto en Prosper."}
          </p>
          <Link href="/" className="prosper-btn-primary mt-5 inline-flex h-10 px-4 text-sm">
            Volver al inicio
          </Link>
        </div>
      </CenterShell>
    );
  }

  const canNext = (): boolean => {
    if (step === 2) {
      return !!(personal.first_name && personal.last_name && personal.dob &&
                personal.nationality && personal.doc_id);
    }
    if (step === 3) return !!corpLegalName;
    if (step === 4) {
      const filled = ubos.filter((u) => u.full_name.trim().length > 0);
      if (filled.length === 0) return false;
      const total = filled.reduce((s, u) => s + Number(u.ownership_pct || 0), 0);
      return total > 0 && total <= 100;
    }
    if (step === 5) {
      return DOC_KINDS.filter((d) => ["certificate", "board_resolution", "tax_id"].includes(d.key))
                     .every((d) => docs[d.key]);
    }
    if (step === 7) return accept;
    return true;
  };

  const submit = async () => {
    setSubmitting(true);
    try {
      const payload: ApplyPayload = {
        token,
        personal,
        corporate: { legal_name: corpLegalName },
        ubos: ubos.filter((u) => u.full_name.trim().length > 0)
                  .map((u) => ({ ...u, ownership_pct: Number(u.ownership_pct) })),
        documents: Object.entries(docs)
          .filter(([, v]) => v)
          .map(([k]) => {
            const meta = DOC_KINDS.find((d) => d.key === k);
            return { label: meta?.label || k, kind: k, url: `placeholder://${k}` };
          }),
        accept_terms: accept,
      };
      const res = await api<{ ok: boolean; case_id: string }>(
        "/v1/apply/finalize",
        { method: "POST", body: JSON.stringify(payload) }
      );
      toast.success("Onboarding enviado. Compliance fue notificado.");
      router.push(`/apply/status?app_id=${res.case_id}`);
    } catch (err) {
      const e = err as Error;
      toast.error(e.message || "Error al enviar");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-bg" data-testid="apply-wizard">
      <header className="border-b border-border bg-surface">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <ProsperLogo />
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
            KYB onboarding · {ctx.commercial_name || ctx.legal_name}
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-10">
        {/* Stepper */}
        <ol className="hidden md:flex items-center gap-2 mb-8" data-testid="apply-stepper">
          {STEPS.map((s, i) => {
            const done = step > s.id;
            const active = step === s.id;
            return (
              <li key={s.id} className="flex items-center gap-2 flex-1 last:flex-none">
                <div
                  className={`h-7 w-7 rounded-full flex items-center justify-center text-[11px] font-mono font-bold border
                              ${done ? "bg-success text-white border-success"
                                : active ? "bg-primary text-white border-primary"
                                : "bg-bg text-fg-subtle border-border"}`}
                  data-testid={`step-${s.id}`}
                  data-active={active}
                  data-done={done}
                >
                  {done ? <CheckCircle2 size={12} /> : s.id}
                </div>
                <div className={`text-[11px] uppercase tracking-wider font-mono whitespace-nowrap
                                ${active ? "text-fg font-bold" : "text-fg-subtle"}`}>
                  {s.label}
                </div>
                {i < STEPS.length - 1 && (
                  <div className={`flex-1 h-px ${done ? "bg-success" : "bg-border"}`} />
                )}
              </li>
            );
          })}
        </ol>

        <div className="prosper-card p-7">
          {step === 1 && <StepWelcome ctx={ctx} />}
          {step === 2 && <StepPersonal data={personal} onChange={setPersonal} />}
          {step === 3 && (
            <StepCorporate ctx={ctx} legalName={corpLegalName} setLegalName={setCorpLegalName} />
          )}
          {step === 4 && <StepUbos ubos={ubos} setUbos={setUbos} />}
          {step === 5 && <StepDocuments docs={docs} setDocs={setDocs} />}
          {step === 6 && <StepVerification ctx={ctx} token={token!}
                                              personal={personal}
                                              corpLegalName={corpLegalName} />}
          {step === 7 && (
            <StepReview
              ctx={ctx}
              personal={personal}
              corpLegalName={corpLegalName}
              ubos={ubos}
              docs={docs}
              accept={accept}
              setAccept={setAccept}
            />
          )}
        </div>

        {/* Footer nav */}
        <div className="mt-6 flex items-center justify-between">
          <button
            type="button"
            onClick={() => setStep((s) => Math.max(1, s - 1))}
            disabled={step === 1}
            className="prosper-btn-ghost h-11 px-4 text-sm gap-2 disabled:opacity-30"
            data-testid="apply-back"
          >
            <ArrowLeft size={14} /> Atrás
          </button>

          {step < STEPS.length ? (
            <button
              type="button"
              onClick={() => canNext() && setStep((s) => s + 1)}
              disabled={!canNext()}
              className="prosper-btn-primary h-11 px-6 text-sm gap-2 disabled:opacity-40"
              data-testid="apply-next"
            >
              Siguiente <ArrowRight size={14} />
            </button>
          ) : (
            <button
              type="button"
              onClick={submit}
              disabled={!canNext() || submitting}
              className="prosper-btn-primary h-11 px-6 text-sm gap-2 disabled:opacity-40"
              data-testid="apply-submit"
            >
              {submitting ? "Enviando…" : (<>Enviar para revisión <CheckCircle2 size={14} /></>)}
            </button>
          )}
        </div>
      </main>
    </div>
  );
}

/* ---------------- Steps ---------------- */

function StepWelcome({ ctx }: { ctx: ApplyContext }) {
  return (
    <div data-testid="step-content-1">
      <Kicker>Paso 1 / 7 · Bienvenida</Kicker>
      <Title>Hola {ctx.primary_name?.split(" ")[0] || ctx.commercial_name}</Title>
      <p className="text-sm text-fg-muted max-w-xl">
        Vamos a completar el KYB de <strong>{ctx.commercial_name || ctx.legal_name}</strong>.
        Te tomará 5–10 minutos. Podés guardar y volver con el mismo link.
      </p>
      <div className="mt-5 grid grid-cols-2 gap-4 text-sm">
        <Pre label="Razón social"  value={ctx.legal_name} />
        <Pre label="País"          value={ctx.country} />
        <Pre label="Tax ID"        value={ctx.tax_id} />
        <Pre label="Tipo"          value={ctx.type} />
      </div>
    </div>
  );
}

function StepPersonal({ data, onChange }:
  { data: PersonalData; onChange: (d: PersonalData) => void }) {
  const set = (k: keyof PersonalData, v: string) => onChange({ ...data, [k]: v });
  return (
    <div data-testid="step-content-2">
      <Kicker>Paso 2 / 7 · Tu identidad</Kicker>
      <Title>¿Quién está completando este onboarding?</Title>
      <p className="text-sm text-fg-muted mb-5">
        Necesitamos verificar la identidad de la persona responsable de la cuenta.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <FormField label="Nombre *"     value={data.first_name} onChange={(v) => set("first_name", v)} testid="first-name" />
        <FormField label="Apellido *"   value={data.last_name}  onChange={(v) => set("last_name", v)} testid="last-name" />
        <FormField label="Fecha nac. *" type="date" value={data.dob} onChange={(v) => set("dob", v)} testid="dob" />
        <FormField label="Género"        value={data.gender} onChange={(v) => set("gender", v)}
                   placeholder="M / F / Otro" testid="gender" />
        <FormField label="Nacionalidad *" value={data.nationality} onChange={(v) => set("nationality", v)}
                   placeholder="AR" testid="nationality" />
        <FormField label="DNI / Pasaporte *" value={data.doc_id} onChange={(v) => set("doc_id", v)} testid="doc-id" />
      </div>
    </div>
  );
}

function StepCorporate({ ctx, legalName, setLegalName }:
  { ctx: ApplyContext; legalName: string; setLegalName: (v: string) => void }) {
  return (
    <div data-testid="step-content-3">
      <Kicker>Paso 3 / 7 · Empresa</Kicker>
      <Title>Confirmá los datos corporativos</Title>
      <p className="text-sm text-fg-muted mb-5">
        Ya tenemos lo principal del registro. Confirmá la razón social tal como
        figura en el certificado de constitución.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <FormField label="Razón social *" value={legalName} onChange={setLegalName} testid="legal-name" />
        <Pre label="Nombre comercial" value={ctx.commercial_name} />
        <Pre label="País"             value={ctx.country} />
        <Pre label="Tax ID"           value={ctx.tax_id} />
      </div>
    </div>
  );
}

function StepUbos({ ubos, setUbos }:
  { ubos: UBOInput[]; setUbos: (u: UBOInput[]) => void }) {
  const total = ubos.reduce((s, u) => s + Number(u.ownership_pct || 0), 0);
  return (
    <div data-testid="step-content-4">
      <Kicker>Paso 4 / 7 · UBOs</Kicker>
      <Title>Beneficiarios finales (UBOs)</Title>
      <p className="text-sm text-fg-muted mb-5">
        Cargá a todas las personas físicas con &gt;25% de la empresa, o que ejerzan
        control. El total no puede superar 100%.
      </p>

      <div className="space-y-3">
        {ubos.map((u, i) => (
          <div key={i} className="grid grid-cols-12 gap-2 items-end" data-testid={`ubo-row-${i}`}>
            <div className="col-span-4">
              <FormField label={i === 0 ? "Nombre completo *" : ""} value={u.full_name}
                onChange={(v) => setUbos(ubos.map((x, idx) => idx === i ? { ...x, full_name: v } : x))}
                testid={`ubo-${i}-name`} />
            </div>
            <div className="col-span-2">
              <FormField label={i === 0 ? "% participación *" : ""} type="number"
                value={String(u.ownership_pct)}
                onChange={(v) => setUbos(ubos.map((x, idx) => idx === i ? { ...x, ownership_pct: Number(v) } : x))}
                testid={`ubo-${i}-pct`} />
            </div>
            <div className="col-span-3">
              <FormField label={i === 0 ? "Nacionalidad" : ""} value={u.nationality || ""}
                placeholder="AR"
                onChange={(v) => setUbos(ubos.map((x, idx) => idx === i ? { ...x, nationality: v } : x))}
                testid={`ubo-${i}-nat`} />
            </div>
            <div className="col-span-2">
              <label className="block">
                {i === 0 && (
                  <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-1">
                    ¿Es PEP?
                  </div>
                )}
                <select
                  className="prosper-input w-full h-10 text-sm"
                  value={u.is_pep ? "yes" : "no"}
                  onChange={(e) => setUbos(ubos.map((x, idx) =>
                    idx === i ? { ...x, is_pep: e.target.value === "yes" } : x))}
                  data-testid={`ubo-${i}-pep`}
                >
                  <option value="no">No</option>
                  <option value="yes">Sí</option>
                </select>
              </label>
            </div>
            <div className="col-span-1">
              {ubos.length > 1 && (
                <button type="button"
                  onClick={() => setUbos(ubos.filter((_, idx) => idx !== i))}
                  className="h-10 w-full text-xs text-danger hover:bg-danger/10 rounded"
                  data-testid={`ubo-${i}-remove`}>×</button>
              )}
            </div>
          </div>
        ))}
        <div className="flex items-center justify-between pt-2">
          <button type="button"
            onClick={() => setUbos([...ubos, { full_name: "", ownership_pct: 0, nationality: "", is_pep: false }])}
            className="text-xs font-mono uppercase tracking-wider text-primary hover:underline"
            data-testid="ubo-add">+ Agregar UBO</button>
          <div className={`text-[11px] font-mono ${total > 100 ? "text-danger" : "text-fg-muted"}`}
               data-testid="ubo-total">
            Total · {total}% {total > 100 && "(supera 100%)"}
          </div>
        </div>
      </div>
    </div>
  );
}

function StepDocuments({ docs, setDocs }:
  { docs: Record<string, boolean>; setDocs: (d: Record<string, boolean>) => void }) {
  const toggle = (k: string) => setDocs({ ...docs, [k]: !docs[k] });
  return (
    <div data-testid="step-content-5">
      <Kicker>Paso 5 / 7 · Documentos</Kicker>
      <Title>Cargá la documentación corporativa</Title>
      <p className="text-sm text-fg-muted mb-5">
        Los documentos marcados con * son obligatorios. (Upload se realiza
        directamente en el widget de Alfred en el siguiente paso — confirmá
        que los tenés listos para subir.)
      </p>
      <ul className="space-y-2">
        {DOC_KINDS.map((d) => {
          const required = ["certificate", "board_resolution", "tax_id"].includes(d.key);
          const checked = !!docs[d.key];
          return (
            <li key={d.key}>
              <label
                className={`flex items-center gap-3 p-3 rounded border cursor-pointer transition-colors
                            ${checked ? "border-primary bg-primary/5" : "border-border hover:bg-surface-hover"}`}
                data-testid={`doc-${d.key}`}
              >
                <input type="checkbox" checked={checked} onChange={() => toggle(d.key)}
                       data-testid={`doc-cb-${d.key}`}
                       className="h-4 w-4 rounded border-border text-primary" />
                <div className="flex-1">
                  <div className="text-sm font-display font-semibold text-fg">
                    {d.label} {required && <span className="text-danger">*</span>}
                  </div>
                  <div className="text-[11px] text-fg-subtle">
                    {checked ? "Listo para enviar" : "Pendiente"}
                  </div>
                </div>
                <FileUp size={14} className="text-fg-subtle" />
              </label>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function StepVerification({ ctx, token, personal, corpLegalName }:
  { ctx: ApplyContext; token: string;
    personal: PersonalData; corpLegalName: string }) {
  const [iframeUrl, setIframeUrl] = useState<string | null>(null);
  const [customerId, setCustomerId] = useState<string | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "in_iframe" | "approved" | "rejected" | "error">("idle");
  const [mode, setMode] = useState<string>("");
  const [errorMsg, setErrorMsg] = useState<string>("");

  // Kick off Alfred KYB customer creation once when user enters this step.
  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    api<{ customer_id: string; iframe_url: string; status: string; mode: string }>(
      "/v1/onboarding/alfred/kyb/start",
      {
        method: "POST",
        body: JSON.stringify({
          token,
          legal_name: corpLegalName || ctx.legal_name,
          primary_email: ctx.primary_email,
          country: ctx.country,
          applicant: {
            first_name: personal.first_name,
            last_name:  personal.last_name,
            dob:        personal.dob,
            nationality: personal.nationality,
            doc_id:     personal.doc_id,
          },
        }),
      }
    )
      .then((r) => {
        if (cancelled) return;
        setIframeUrl(r.iframe_url);
        setCustomerId(r.customer_id);
        setMode(r.mode);
        setStatus(r.status === "approved" ? "approved" : "in_iframe");
      })
      .catch((e: Error) => {
        if (cancelled) return;
        setErrorMsg(e.message || "Error iniciando KYB");
        setStatus("error");
      });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Listen for postMessage from iframe (mock or future real)
  useEffect(() => {
    const onMsg = (ev: MessageEvent) => {
      const d = ev.data;
      if (typeof d !== "object" || !d) return;
      if (d.type === "alfred:kyc:approve") {
        setStatus("approved");
        toast.success("KYB aprobado por Alfred");
      } else if (d.type === "alfred:kyc:reject") {
        setStatus("rejected");
        toast.error("KYB rechazado");
      }
    };
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, []);

  // Poll backend status every 3s as a fallback (webhook may approve while
  // iframe focus is elsewhere — covers real-Alfred case too).
  useEffect(() => {
    if (!customerId || status === "approved" || status === "rejected") return;
    const tick = async () => {
      try {
        const r = await api<{ alfred_status: string; kyb_status: string }>(
          `/v1/onboarding/alfred/status?customer_id=${encodeURIComponent(customerId)}`
        );
        if (r.alfred_status === "approved" || r.kyb_status === "approved") {
          setStatus("approved");
        } else if (r.alfred_status === "rejected") {
          setStatus("rejected");
        }
      } catch { /* ignore */ }
    };
    const id = setInterval(tick, 3000);
    return () => clearInterval(id);
  }, [customerId, status]);

  return (
    <div data-testid="step-content-6">
      <Kicker>Paso 6 / 7 · Verificación</Kicker>
      <Title>Verificación de identidad con Alfred</Title>
      <p className="text-sm text-fg-muted mb-5">
        Completá KYB hospedado por <strong>Alfred Pay</strong>. Captura de
        documento corporativo, identidad del firmante y prueba de domicilio.
        El resultado llega automáticamente vía webhook.
      </p>

      {status === "loading" && (
        <div className="rounded-lg border border-border bg-surface p-6 text-sm text-fg-muted"
             data-testid="alfred-kyb-loading">
          Iniciando sesión con Alfred…
        </div>
      )}

      {status === "error" && (
        <div className="rounded-lg border border-danger/40 bg-danger/5 p-5 text-sm text-danger"
             data-testid="alfred-kyb-error">
          {errorMsg}
        </div>
      )}

      {iframeUrl && (status === "in_iframe" || status === "approved" || status === "rejected") && (
        <div className="rounded-lg border border-border bg-surface overflow-hidden"
             data-testid="alfred-kyb-iframe-wrap">
          <div className="px-4 py-2 flex items-center justify-between border-b border-border bg-bg">
            <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
              Alfred · {mode === "mock" ? "Mock KYB widget" : "KYB"}
              {customerId && <> · <code className="text-fg">{customerId.slice(0, 18)}</code></>}
            </div>
            <span className={`text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded-full
                              ${status === "approved" ? "bg-success/20 text-success"
                                : status === "rejected" ? "bg-danger/20 text-danger"
                                : "bg-warning/20 text-warning"}`}
                  data-testid="alfred-kyb-status">
              {status === "approved" ? "Aprobado"
                : status === "rejected" ? "Rechazado"
                : "Pendiente"}
            </span>
          </div>
          <iframe
            src={iframeUrl}
            title="Alfred KYB"
            data-testid="alfred-kyb-iframe"
            className="w-full"
            style={{ height: 520, border: 0, background: "#0B0F19" }}
            allow="camera; microphone; clipboard-read; clipboard-write"
          />
          {status !== "approved" && (
            <div className="px-4 py-3 text-[11px] text-fg-subtle bg-bg border-t border-border">
              También podés{" "}
              <a href={iframeUrl} target="_blank" rel="noopener noreferrer"
                 className="text-primary hover:underline" data-testid="alfred-kyb-popout">
                abrir en una nueva ventana
              </a>
              . Esta sección se actualiza automáticamente al finalizar.
            </div>
          )}
        </div>
      )}

      <div className="mt-4 rounded-lg border border-border bg-surface p-4 text-xs text-fg-muted">
        <strong className="text-fg">Email de notificación:</strong> {ctx.primary_email}
      </div>
    </div>
  );
}

function StepReview({ ctx, personal, corpLegalName, ubos, docs, accept, setAccept }:
  { ctx: ApplyContext; personal: PersonalData; corpLegalName: string;
    ubos: UBOInput[]; docs: Record<string, boolean>;
    accept: boolean; setAccept: (b: boolean) => void }) {
  const filled = ubos.filter((u) => u.full_name.trim().length > 0);
  const docCount = Object.values(docs).filter(Boolean).length;
  return (
    <div data-testid="step-content-7">
      <Kicker>Paso 7 / 7 · Revisar y enviar</Kicker>
      <Title>Casi listo</Title>
      <p className="text-sm text-fg-muted mb-5">
        Confirmá los datos. Una vez enviado, compliance los revisará y te
        notificaremos por email.
      </p>
      <div className="space-y-4 text-sm">
        <ReviewBlock label="Empresa" items={[
          ["Razón social",   corpLegalName],
          ["Nombre comercial", ctx.commercial_name],
          ["País",           ctx.country],
          ["Tax ID",         ctx.tax_id],
        ]} />
        <ReviewBlock label="Aplicante" items={[
          ["Nombre completo", `${personal.first_name} ${personal.last_name}`],
          ["Nacionalidad",    personal.nationality],
          ["Documento",       personal.doc_id],
          ["Fecha nac.",      personal.dob],
        ]} />
        <div className="rounded border border-border p-4">
          <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-2">
            UBOs ({filled.length})
          </div>
          <ul className="space-y-1 text-xs text-fg-muted" data-testid="review-ubos">
            {filled.map((u, i) => (
              <li key={i}>• {u.full_name} — {u.ownership_pct}%{u.is_pep ? " · PEP" : ""}</li>
            ))}
          </ul>
        </div>
        <div className="rounded border border-border p-4 flex items-center justify-between">
          <span className="text-fg-muted">Documentos preparados</span>
          <span className="font-mono text-fg">{docCount} / {DOC_KINDS.length}</span>
        </div>
      </div>

      <label className="flex items-start gap-3 mt-6 p-3 rounded border border-border bg-surface cursor-pointer"
             data-testid="apply-terms">
        <input type="checkbox" checked={accept} onChange={(e) => setAccept(e.target.checked)}
               className="h-4 w-4 mt-0.5 rounded border-border text-primary"
               data-testid="apply-terms-cb" />
        <span className="text-xs text-fg-muted">
          Confirmo que la información provista es verdadera y completa. Acepto los{" "}
          <a href="/terms" className="text-primary hover:underline">Términos</a> y la{" "}
          <a href="/privacy" className="text-primary hover:underline">Política de Privacidad</a> de Prosper.
        </span>
      </label>
    </div>
  );
}

/* ---------------- Bits ---------------- */

function CenterShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-bg p-6">{children}</div>
  );
}

function Kicker({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-1">
      {children}
    </div>
  );
}
function Title({ children }: { children: React.ReactNode }) {
  return <h1 className="font-display font-bold text-2xl text-fg tracking-tight mb-3">{children}</h1>;
}

function Pre({ label, value }: { label: string; value?: string | null }) {
  return (
    <div>
      <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-1">
        {label}
      </div>
      <div className="text-sm text-fg font-mono">{value || "—"}</div>
    </div>
  );
}

function ReviewBlock({ label, items }:
  { label: string; items: Array<[string, string | undefined | null]> }) {
  return (
    <div className="rounded border border-border p-4" data-testid={`review-${label.toLowerCase()}`}>
      <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-2">
        {label}
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
        {items.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-fg-muted">{k}</dt>
            <dd className="text-fg font-mono">{v || "—"}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function FormField({ label, value, onChange, placeholder, type = "text", testid }:
  { label: string; value: string; onChange: (v: string) => void;
    placeholder?: string; type?: string; testid: string }) {
  return (
    <label className="block">
      {label && (
        <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-1">
          {label}
        </div>
      )}
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="prosper-input w-full h-10 text-sm"
        data-testid={`apply-${testid}`}
      />
    </label>
  );
}
