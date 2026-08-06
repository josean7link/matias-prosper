"use client";
import Link from "next/link";
import useSWR from "swr";
import { useSearchParams } from "next/navigation";
import { ArrowRight, CheckCircle2, Clock, XCircle, RefreshCw, Camera } from "lucide-react";
import { ProsperLogo } from "@/components/ProsperLogo";
import { api } from "@/lib/api";
import { Badge } from "@prosper/ui";

interface AppStatus {
  application_id: string;
  org_id: string;
  legal_name: string;
  status: "in_review" | "approved" | "rejected";
  kyb_status: string;
  decision?: string | null;
  submitted_at: string;
  aiprise_mode?: "live" | "simulated" | "andes-direct" | null;
}

export default function ApplyStatusPage() {
  const params = useSearchParams();
  const appId = params.get("app_id");
  const { data, isLoading, mutate } = useSWR<AppStatus>(
    appId ? `/v1/onboarding/apply/${appId}` : null,
    (p: string) => api(p),
    { refreshInterval: 10_000 },
  );

  if (!appId) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-bg">
        <p className="text-fg-subtle text-sm">Missing app_id</p>
      </div>
    );
  }

  const isAndesDirect = data?.aiprise_mode === "andes-direct";
  const showUploadCta = isAndesDirect && data?.status === "in_review";

  return (
    <div className="min-h-screen bg-bg flex items-center justify-center p-6"
         data-testid="apply-status">
      <div className="prosper-card max-w-md w-full p-7 text-center">
        <div className="flex items-center justify-center gap-2 mb-4">
          <ProsperLogo />
        </div>

        {isLoading || !data ? (
          <p className="text-fg-subtle text-sm">Cargando…</p>
        ) : data.status === "approved" ? (
          <Result
            icon={<CheckCircle2 size={56} className="text-success mx-auto" />}
            title="¡Cuenta aprobada!"
            msg={`Bienvenido, ${data.legal_name}. Tu cuenta está activa y lista para operar.`}
            testid="status-approved"
            cta={{
              href: "/login",
              label: "Ingresar al portal",
              testid: "status-approved-cta",
            }}
          />
        ) : data.status === "rejected" ? (
          <Result
            icon={<XCircle size={56} className="text-danger mx-auto" />}
            title="Solicitud rechazada"
            msg={data.decision
              ? `Motivo: ${data.decision}`
              : "Compliance no pudo aprobar la cuenta. Escribinos para revisar el caso."}
            testid="status-rejected"
          />
        ) : (
          <Result
            icon={<Clock size={56} className="text-warning mx-auto" />}
            title={showUploadCta ? "Faltan tus fotos" : "En revisión"}
            msg={showUploadCta
              ? "Para terminar la verificación necesitamos tus 3 fotos (selfie + DNI frente y dorso)."
              : "Recibimos tu solicitud y compliance la está revisando. Te avisamos por email en menos de 1 día hábil."}
            testid="status-pending"
            cta={showUploadCta
              ? {
                  href: `/apply/${data.application_id}/kyc-docs`,
                  label: "Subir mis fotos",
                  testid: "status-upload-cta",
                  icon: <Camera size={14} />,
                }
              : undefined}
          />
        )}

        {data && (
          <div className="mt-6 pt-4 border-t border-border text-left
                          text-[11px] font-mono text-fg-subtle space-y-1">
            <div>app_id · {data.application_id}</div>
            <div>org_id · {data.org_id}</div>
            <div>
              kyb_status · <Badge tone="auto" size="sm">{data.kyb_status}</Badge>
              {data.aiprise_mode === "simulated" && (
                <span className="ml-2 inline-block text-[9px] uppercase
                                  tracking-wider bg-warning/10 text-warning px-1.5 py-0.5 rounded">
                  sim
                </span>
              )}
              {isAndesDirect && (
                <span className="ml-2 inline-block text-[9px] uppercase
                                  tracking-wider bg-primary/10 text-primary px-1.5 py-0.5 rounded">
                  Andes
                </span>
              )}
            </div>
          </div>
        )}

        <div className="mt-5 flex items-center justify-between text-xs">
          <Link href="/" className="text-fg-subtle hover:text-fg
                                     font-mono uppercase tracking-wider"
                data-testid="status-home">
            Inicio
          </Link>
          <button onClick={() => mutate()}
                  data-testid="status-refresh"
                  className="text-primary font-mono uppercase tracking-wider
                             flex items-center gap-1 hover:underline">
            <RefreshCw size={11} /> Refrescar
          </button>
        </div>
      </div>
    </div>
  );
}

function Result({ icon, title, msg, testid, cta }:
  { icon: React.ReactNode; title: string; msg: string; testid: string;
    cta?: { href: string; label: string; testid: string; icon?: React.ReactNode } }) {
  return (
    <div data-testid={testid}>
      {icon}
      <h1 className="font-display font-bold text-xl text-fg mt-3">{title}</h1>
      <p className="text-sm text-fg-muted mt-2 max-w-xs mx-auto">{msg}</p>
      {cta && (
        <Link
          href={cta.href}
          data-testid={cta.testid}
          className="prosper-btn-primary h-11 px-5 text-sm gap-2 mt-5 inline-flex"
        >
          {cta.icon} {cta.label} <ArrowRight size={14}/>
        </Link>
      )}
    </div>
  );
}
