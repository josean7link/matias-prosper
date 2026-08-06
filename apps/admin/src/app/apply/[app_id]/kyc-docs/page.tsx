"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import {
  ArrowRight, ArrowLeft, Camera, CheckCircle2, Loader2,
  RefreshCw, Sparkles, Sun, User as UserIcon, IdCard, XCircle,
} from "lucide-react";
import { ProsperLogo } from "@/components/ProsperLogo";
import { Badge } from "@prosper/ui";

type DocKey = "face" | "id_front" | "id_back";

interface ShotMeta {
  blob: Blob;
  preview: string;
  size: number;
  filename: string;
}

interface ApplyStatus {
  application_id: string;
  org_id: string;
  legal_name: string;
  status: "in_review" | "approved" | "rejected";
  kyb_status: string;
  sanctions_status?: "pending" | "clear" | "flagged";
  andes_onboarding_status?: string | null;
  decision?: string | null;
  submitted_at: string;
  aiprise_mode?: string | null;
}

const DOCS: { key: DocKey; title: string; help: string; icon: React.ReactNode }[] = [
  {
    key: "face",
    title: "Selfie",
    help: "Mirá de frente, sin lentes ni gorra. Buena luz natural.",
    icon: <UserIcon size={18} />,
  },
  {
    key: "id_front",
    title: "DNI · Frente",
    help: "Apoyalo sobre una superficie oscura, sin reflejos.",
    icon: <IdCard size={18} />,
  },
  {
    key: "id_back",
    title: "DNI · Dorso",
    help: "Que se vean los 4 bordes y el código de barras nítido.",
    icon: <IdCard size={18} />,
  },
];

const MIN_BYTES = 8 * 1024;       // 8KB lower bound
const MAX_BYTES = 6 * 1024 * 1024; // 6MB per file

async function jsonFetcher<T>(path: string): Promise<T> {
  const url = `/api${path.startsWith("/") ? path : "/" + path}`;
  const r = await fetch(url, { credentials: "include" });
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json();
}

export default function KycDocsPage() {
  const params = useParams<{ app_id: string }>();
  const router = useRouter();
  const appId = params?.app_id;

  // ---- App existence + status (polled after submit) ----
  const { data: app, error: appErr, mutate: refreshApp } = useSWR<ApplyStatus>(
    appId ? `/v1/onboarding/apply/${appId}` : null,
    jsonFetcher,
    { refreshInterval: 0 },
  );

  // ---- Photo state ----
  const [shots, setShots] = useState<Record<DocKey, ShotMeta | null>>({
    face: null, id_front: null, id_back: null,
  });
  const [phase, setPhase] = useState<
    "capture" | "uploading" | "polling" | "sanctions" | "approved" | "rejected"
  >("capture");
  const [rejectReason, setRejectReason] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);

  const setShot = useCallback((key: DocKey, meta: ShotMeta | null) => {
    setShots((prev) => {
      // free old preview URL
      if (prev[key]?.preview) URL.revokeObjectURL(prev[key]!.preview);
      return { ...prev, [key]: meta };
    });
  }, []);

  const ready = !!(shots.face && shots.id_front && shots.id_back);

  // ---- Submit ----
  const submit = async () => {
    if (!ready || !appId) return;
    setPhase("uploading");
    setUploadProgress(15);
    // Abort if Andes hangs > 90s — UX safety net (user can retry)
    const ctrl = new AbortController();
    const abortTimer = setTimeout(() => ctrl.abort(), 90_000);
    try {
      const fd = new FormData();
      (Object.keys(shots) as DocKey[]).forEach((k) => {
        const meta = shots[k]!;
        fd.append(k, meta.blob, meta.filename);
      });
      setUploadProgress(35);
      const url = `/api/v1/onboarding/${appId}/kyc-docs`;
      const r = await fetch(url, {
        method: "POST", credentials: "include", body: fd, signal: ctrl.signal,
      });
      setUploadProgress(90);
      if (!r.ok) {
        let detail = `Error ${r.status}`;
        try {
          const j = await r.json();
          detail = (j.detail as string) || detail;
        } catch { /* ignore */ }
        // 422 / 502 / 500 with quality keywords → show rejected screen with tips
        const looksLikeQualityIssue =
          r.status === 422 ||
          /unsupported image|nít|calidad|borrosa|blurry|quality|fotos/i.test(detail);
        if (looksLikeQualityIssue) {
          setPhase("rejected");
          setRejectReason(
            r.status === 422
              ? detail
              : "Andes no pudo procesar las fotos. Sacalas de nuevo con mejor luz y los 4 bordes del DNI visibles."
          );
          return;
        }
        if (r.status === 409) {
          setPhase("polling");
          await refreshApp();
          return;
        }
        toast.error(detail);
        setPhase("capture");
        return;
      }
      const out = await r.json();
      setUploadProgress(100);
      toast.success("Fotos enviadas. Estamos validando con Andes…");
      // Andes already approved + sanctions cleared synchronously? Skip directly to approved
      if (out.kyb_status === "approved" && out.sanctions_status === "clear") {
        setPhase("approved");
      } else if (out.onboarding_status === "approved" || out.next === "portal") {
        // Andes OK but sanctions still pending → show sanctions screen
        setPhase("sanctions");
      } else {
        setPhase("polling");
      }
      refreshApp();
    } catch (e) {
      const err = e as Error;
      if (err.name === "AbortError") {
        setPhase("rejected");
        setRejectReason(
          "Andes está tardando más de lo normal. Probá de nuevo en un momento — si persiste, revisá la nitidez de las fotos."
        );
        return;
      }
      toast.error(err.message || "No pudimos subir las fotos");
      setPhase("capture");
    } finally {
      clearTimeout(abortTimer);
    }
  };

  // ---- Poll status while validating ----
  useEffect(() => {
    if (!["polling", "sanctions"].includes(phase) || !appId) return;
    const id = setInterval(async () => {
      try {
        const r = await refreshApp();
        if (!r) return;
        const kyb = r.kyb_status;
        const sanc = r.sanctions_status || "pending";
        const andesOk =
          (r.andes_onboarding_status === "approved") ||
          (r.andes_onboarding_status === "completed");
        // Full activation: KYB approved + sanctions clear
        if (kyb === "approved" && sanc === "clear") {
          setPhase("approved");
          clearInterval(id);
          return;
        }
        if (sanc === "flagged" || kyb === "rejected") {
          setPhase("rejected");
          setRejectReason(
            sanc === "flagged"
              ? "Compliance detectó un match en listas de sanciones/PEP. Te vamos a contactar por email."
              : (r.decision || "La verificación fue rechazada.")
          );
          clearInterval(id);
          return;
        }
        // Andes done, waiting on sanctions
        if (andesOk && sanc === "pending") {
          setPhase("sanctions");
          return;
        }
      } catch { /* keep polling */ }
    }, 4000);
    return () => clearInterval(id);
  }, [phase, appId, refreshApp]);

  // ---- Render ----
  if (!appId) return null;

  if (appErr) {
    return (
      <Shell>
        <div className="prosper-card p-7 text-center max-w-md mx-auto"
             data-testid="kyc-docs-error">
          <XCircle size={40} className="text-danger mx-auto mb-3" />
          <h1 className="font-display font-bold text-lg">No encontramos tu solicitud</h1>
          <p className="text-sm text-fg-muted mt-2">
            El link puede haber expirado. Volvé a abrir tu cuenta en{" "}
            <Link href="/apply" className="text-primary hover:underline">/apply</Link>.
          </p>
        </div>
      </Shell>
    );
  }

  return (
    <Shell>
      <div className="max-w-3xl mx-auto" data-testid="kyc-docs-page">
        <div className="mb-6">
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-1">
            Verificación de identidad · Andes
          </div>
          <h1 className="font-display font-bold text-3xl text-fg tracking-tight">
            Subí tus 3 fotos
          </h1>
          <p className="text-sm text-fg-muted mt-2 max-w-xl">
            Las usamos para confirmar que sos vos. Validación automática y al instante.
            {app && (
              <span className="ml-1 text-fg-subtle font-mono text-[11px]">
                · app {app.application_id.slice(-8)}
              </span>
            )}
          </p>
        </div>

        {/* --- Phase: approved --- */}
        {phase === "approved" && (
          <ApprovedView appId={appId} />
        )}

        {/* --- Phase: rejected --- */}
        {phase === "rejected" && (
          <RejectedView
            reason={rejectReason}
            onRetry={() => {
              setShots({ face: null, id_front: null, id_back: null });
              setPhase("capture");
              setRejectReason(null);
            }}
          />
        )}

        {/* --- Phase: polling --- */}
        {phase === "polling" && <PollingView />}

        {/* --- Phase: sanctions (Andes ok, awaiting compliance) --- */}
        {phase === "sanctions" && <SanctionsView />}

        {/* --- Phase: uploading --- */}
        {phase === "uploading" && <UploadingView pct={uploadProgress} />}

        {/* --- Phase: capture --- */}
        {phase === "capture" && (
          <>
            <PhotoTips />

            <div className="space-y-4 mb-8" data-testid="kyc-docs-slots">
              {DOCS.map((d) => (
                <DocSlot
                  key={d.key}
                  spec={d}
                  shot={shots[d.key]}
                  onChange={(meta) => setShot(d.key, meta)}
                />
              ))}
            </div>

            <div className="flex items-center justify-between border-t border-border pt-6">
              <Link
                href="/apply"
                className="prosper-btn-ghost h-11 px-4 text-sm gap-2"
                data-testid="kyc-docs-back"
              >
                <ArrowLeft size={14} /> Volver
              </Link>
              <button
                type="button"
                onClick={submit}
                disabled={!ready}
                className="prosper-btn-primary h-11 px-6 text-sm gap-2 disabled:opacity-40"
                data-testid="kyc-docs-submit"
              >
                Enviar para validación <ArrowRight size={14} />
              </button>
            </div>
          </>
        )}
      </div>
    </Shell>
  );
}

/* ============================ Sub-components ============================ */

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-bg">
      <header className="border-b border-border bg-surface">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <Link href="/"><ProsperLogo /></Link>
          <Link
            href="/login"
            className="text-xs font-mono uppercase tracking-wider text-fg-subtle hover:text-fg"
          >
            Ya tengo cuenta →
          </Link>
        </div>
      </header>
      <main className="max-w-5xl mx-auto px-6 py-10">{children}</main>
    </div>
  );
}

function PhotoTips() {
  return (
    <div
      className="prosper-card p-5 mb-6"
      data-testid="kyc-docs-tips"
    >
      <div className="flex items-center gap-2 mb-3">
        <Sparkles size={14} className="text-primary" />
        <h2 className="text-sm font-display font-bold text-fg">
          Para que Andes apruebe en el primer intento
        </h2>
      </div>
      <ul className="grid sm:grid-cols-3 gap-3 text-xs text-fg-muted">
        {[
          { icon: <Sun size={14}/>,    txt: "Luz natural, sin contraluz ni flash directo." },
          { icon: <Camera size={14}/>, txt: "Cámara estable, sin temblar. Foto nítida." },
          { icon: <IdCard size={14}/>, txt: "Los 4 bordes del DNI visibles, sin recortes." },
        ].map((t, i) => (
          <li key={i} className="flex items-start gap-2">
            <span className="text-primary mt-0.5">{t.icon}</span>
            <span>{t.txt}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function DocSlot({ spec, shot, onChange }: {
  spec: { key: DocKey; title: string; help: string; icon: React.ReactNode };
  shot: ShotMeta | null;
  onChange: (m: ShotMeta | null) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const isFace = spec.key === "face";

  const accept = "image/jpeg,image/png,image/webp,image/heic";
  const captureAttr = isFace ? "user" : "environment";

  const handlePick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (f.size < MIN_BYTES) {
      toast.error("Foto demasiado chica — sacala de nuevo con mejor calidad.");
      e.target.value = "";
      return;
    }
    if (f.size > MAX_BYTES) {
      toast.error("Foto demasiado pesada (máx 6 MB).");
      e.target.value = "";
      return;
    }
    if (!/^image\//.test(f.type)) {
      toast.error("Solo aceptamos imágenes JPG / PNG / WEBP.");
      e.target.value = "";
      return;
    }
    const url = URL.createObjectURL(f);
    onChange({ blob: f, preview: url, size: f.size,
                filename: f.name || `${spec.key}.jpg` });
    e.target.value = "";
  };

  return (
    <div
      className={`rounded-xl border p-4 sm:p-5 flex flex-col sm:flex-row gap-4
                  ${shot ? "border-success/40 bg-success/5" : "border-border bg-surface"}`}
      data-testid={`kyc-slot-${spec.key}`}
      data-filled={!!shot}
    >
      <div className="flex sm:flex-col items-center gap-3 sm:w-24 shrink-0">
        <div className={`h-10 w-10 rounded-full flex items-center justify-center
                         ${shot ? "bg-success/15 text-success" : "bg-primary/10 text-primary"}`}>
          {shot ? <CheckCircle2 size={18}/> : spec.icon}
        </div>
        <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle sm:text-center">
          {spec.key === "face" ? "Foto 1" :
           spec.key === "id_front" ? "Foto 2" : "Foto 3"}
        </div>
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <h3 className="font-display font-bold text-sm text-fg">{spec.title}</h3>
          {shot && <Badge tone="success" size="sm">Cargada</Badge>}
        </div>
        <p className="text-xs text-fg-muted">{spec.help}</p>

        {shot && (
          <div
            className="mt-3 inline-block relative rounded-lg overflow-hidden border border-border"
            data-testid={`kyc-preview-${spec.key}`}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={shot.preview}
              alt={spec.title}
              className="block h-28 w-auto object-cover"
            />
            <div className="absolute bottom-0 left-0 right-0 px-2 py-1
                            text-[10px] font-mono bg-bg/80 text-fg-subtle">
              {(shot.size / 1024).toFixed(0)} KB · {shot.blob.type.split("/")[1]}
            </div>
          </div>
        )}
      </div>

      <div className="flex sm:flex-col sm:items-end gap-2 sm:w-44 shrink-0">
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          capture={captureAttr as "user" | "environment"}
          onChange={handlePick}
          className="hidden"
          data-testid={`kyc-input-${spec.key}`}
        />
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className={shot
            ? "prosper-btn-ghost h-10 px-4 text-xs border border-border gap-1.5"
            : "prosper-btn-primary h-10 px-4 text-xs gap-1.5"}
          data-testid={`kyc-pick-${spec.key}`}
        >
          <Camera size={13}/> {shot ? "Cambiar" : (isFace ? "Sacarme selfie" : "Sacar foto")}
        </button>
        {shot && (
          <button
            type="button"
            onClick={() => onChange(null)}
            className="text-[11px] text-danger hover:underline"
            data-testid={`kyc-clear-${spec.key}`}
          >
            Quitar
          </button>
        )}
      </div>
    </div>
  );
}

function UploadingView({ pct }: { pct: number }) {
  return (
    <div className="prosper-card p-8 text-center" data-testid="kyc-uploading">
      <Loader2 size={36} className="text-primary mx-auto animate-spin mb-3"/>
      <h2 className="font-display font-bold text-lg text-fg">Subiendo fotos…</h2>
      <p className="text-sm text-fg-muted mt-1">No cierres la ventana.</p>
      <div className="mt-4 h-1.5 bg-surface rounded-full overflow-hidden">
        <div
          className="h-full bg-primary transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function PollingView() {
  return (
    <div className="prosper-card p-8 text-center" data-testid="kyc-polling">
      <Loader2 size={36} className="text-primary mx-auto animate-spin mb-3"/>
      <h2 className="font-display font-bold text-lg text-fg">Validando con Andes…</h2>
      <p className="text-sm text-fg-muted mt-2 max-w-md mx-auto">
        Recibimos las fotos. La verificación suele tardar unos segundos.
        Esta página se actualiza automáticamente cuando termine.
      </p>
      <div className="mt-4 text-[11px] font-mono uppercase tracking-wider text-fg-subtle">
        Estado: en revisión
      </div>
    </div>
  );
}

function SanctionsView() {
  return (
    <div className="prosper-card p-8 text-center" data-testid="kyc-sanctions">
      <div className="mx-auto h-12 w-12 rounded-full bg-primary/10 text-primary
                       flex items-center justify-center mb-3">
        <Loader2 size={22} className="animate-spin"/>
      </div>
      <h2 className="font-display font-bold text-lg text-fg">Tu identidad fue validada</h2>
      <p className="text-sm text-fg-muted mt-2 max-w-md mx-auto">
        Andes confirmó tus datos. Estamos completando el último paso —
        <strong> screening de sanciones / PEP </strong> — que corre
        compliance. Suele tardar menos de 1 día hábil.
      </p>
      <p className="text-xs text-fg-subtle mt-3 max-w-md mx-auto">
        Te avisamos por email apenas tu cuenta esté operativa. No hace falta
        que quedes en esta pantalla; podés cerrar la ventana.
      </p>
      <div className="mt-4 text-[11px] font-mono uppercase tracking-wider text-fg-subtle">
        Estado: pending sanctions
      </div>
    </div>
  );
}

function ApprovedView({ appId }: { appId: string }) {
  return (
    <div className="prosper-card p-8 text-center" data-testid="kyc-approved">
      <CheckCircle2 size={48} className="text-success mx-auto mb-3"/>
      <h2 className="font-display font-bold text-2xl text-fg">¡Listo! Tu cuenta está activa</h2>
      <p className="text-sm text-fg-muted mt-2 max-w-md mx-auto">
        Andes verificó tu identidad correctamente. Te emitimos tu CVU y alias.
        Ya podés entrar al portal y empezar a operar.
      </p>
      <div className="mt-6 flex items-center justify-center gap-3">
        <Link
          href="/login"
          className="prosper-btn-primary h-11 px-6 text-sm gap-2"
          data-testid="kyc-approved-cta-login"
        >
          Ingresar al portal <ArrowRight size={14}/>
        </Link>
        <Link
          href={`/apply/status?app_id=${appId}`}
          className="text-xs font-mono uppercase tracking-wider text-fg-subtle hover:text-fg"
        >
          Ver detalle
        </Link>
      </div>
    </div>
  );
}

function RejectedView({ reason, onRetry }:
  { reason: string | null; onRetry: () => void }) {
  return (
    <div className="prosper-card p-8 text-center" data-testid="kyc-rejected">
      <XCircle size={48} className="text-danger mx-auto mb-3"/>
      <h2 className="font-display font-bold text-2xl text-fg">No pudimos verificar tus fotos</h2>
      <p className="text-sm text-fg-muted mt-2 max-w-md mx-auto">
        {reason || "Andes rechazó al menos una de las tres fotos."}
      </p>
      <div className="mt-5 inline-block text-left bg-warning/5 border border-warning/30
                       rounded-lg p-4 text-xs text-fg-muted max-w-md mx-auto"
           data-testid="kyc-rejected-hint">
        <strong className="text-fg block mb-1">Probá estos tips antes de reintentar:</strong>
        <ul className="space-y-1">
          <li>· Sacá la foto con buena luz natural (cerca de una ventana).</li>
          <li>· Apoyá el DNI sobre una superficie oscura para que se distinga.</li>
          <li>· Asegurate que los 4 bordes del DNI estén visibles, sin recortes.</li>
          <li>· La selfie tiene que ser de frente, sin lentes ni gorra.</li>
        </ul>
      </div>
      <div className="mt-6 flex items-center justify-center gap-3">
        <button
          type="button"
          onClick={onRetry}
          className="prosper-btn-primary h-11 px-6 text-sm gap-2"
          data-testid="kyc-rejected-retry"
        >
          <RefreshCw size={14}/> Reintentar
        </button>
      </div>
    </div>
  );
}
