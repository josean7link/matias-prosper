"use client";
import { notFound, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { BadgeCheck, CircleAlert, LoaderCircle } from "lucide-react";
import { api } from "@/lib/api";
import { KybCard, KybShell, buttonCls, kybEnabled }
  from "../_components/KybShell";

type ActivateResp = {
  ok: boolean; portal: string; case_status: string;
  company_name?: string | null;
};

function ActivateInner() {
  const router = useRouter();
  const params = useSearchParams();
  const token = params.get("token") || "";
  const [state, setState] = useState<"working" | "done" | "error">("working");
  const [error, setError] = useState("");
  const [resp, setResp] = useState<ActivateResp | null>(null);
  const fired = useRef(false);

  useEffect(() => {
    if (fired.current || !token) {
      if (!token) { setState("error"); setError("Falta el token de activación."); }
      return;
    }
    fired.current = true;
    api<ActivateResp>("/v1/kyb/signup/activate", {
      method: "POST", body: JSON.stringify({ activation_token: token }),
    })
      .then((r) => { setResp(r); setState("done"); })
      .catch((e: any) => { setError(e?.message || "Enlace inválido"); setState("error"); });
  }, [token]);

  if (state === "working") {
    return (
      <KybCard title="Activando tu cuenta…">
        <div className="flex justify-center my-8" data-testid="kyb-activate-spinner">
          <LoaderCircle size={32} className="text-primary animate-spin" />
        </div>
      </KybCard>
    );
  }

  if (state === "error") {
    return (
      <KybCard title="No pudimos activar tu cuenta">
        <div className="flex justify-center my-6">
          <div className="h-16 w-16 rounded-full bg-danger/10 flex items-center justify-center">
            <CircleAlert size={32} className="text-danger" />
          </div>
        </div>
        <p className="text-sm text-fg-muted text-center mb-6"
           data-testid="kyb-activate-error-message">{error}</p>
        <button className={buttonCls} data-testid="kyb-activate-restart-button"
                onClick={() => router.push("/kyb/signup")}>
          Volver a empezar
        </button>
      </KybCard>
    );
  }

  return (
    <KybCard title="¡Cuenta activada!"
             subtitle={resp?.company_name ? `Organización: ${resp.company_name}` : undefined}>
      <div className="flex justify-center my-6">
        <div className="h-16 w-16 rounded-full bg-success/10 flex items-center justify-center">
          <BadgeCheck size={32} className="text-success" />
        </div>
      </div>
      {/* Placeholder Fase 2: el wizard del expediente llega en la fase
          siguiente. Mostramos el estado actual del caso. */}
      <div className="rounded-lg border border-border bg-bg p-4 mb-6 text-center"
           data-testid="kyb-activate-case-status">
        <p className="text-xs text-fg-muted uppercase tracking-wide mb-1">
          Estado de tu expediente KYB
        </p>
        <p className="text-lg font-semibold text-fg">{resp?.case_status}</p>
        <p className="text-xs text-fg-muted mt-2">
          Muy pronto vas a poder completar la verificación de tu organización
          desde el portal. Te avisaremos por email.
        </p>
      </div>
      <button className={buttonCls} data-testid="kyb-activate-go-portal-button"
              onClick={() => router.push(resp?.portal || "/client")}>
        Ir al portal
      </button>
    </KybCard>
  );
}

export default function KybActivatePage() {
  if (!kybEnabled()) notFound();
  return (
    <KybShell>
      <Suspense fallback={null}>
        <ActivateInner />
      </Suspense>
    </KybShell>
  );
}
