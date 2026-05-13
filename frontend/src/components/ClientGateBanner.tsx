"use client";
import Link from "next/link";
import { AlertTriangle, Clock, XCircle, PauseCircle, ArrowRight } from "lucide-react";
import { useClientMe } from "@/lib/client-portal";

/**
 * Sticky onboarding/gate banner for the Client portal.
 * Shown when `kyb_status != approved` OR `paused == true`.
 * Tone & copy adapt to the current state.
 */
export function ClientGateBanner() {
  const { data } = useClientMe();
  if (!data) return null;
  const org = data.org;
  const paused = org.paused;

  if (org.kyb_status === "approved" && !paused) return null;

  let tone: "warning" | "info" | "danger" = "warning";
  let icon = <Clock size={16} />;
  let title = "Onboarding pendiente";
  let msg = "Completá tu verificación KYB para habilitar las operaciones.";
  let cta: { href: string; label: string } | null = {
    href: "/apply", label: "Continuar onboarding",
  };

  if (paused) {
    tone = "danger";
    icon = <PauseCircle size={16} />;
    title = "Cuenta pausada";
    msg = "Tu cuenta fue pausada por compliance. Las operaciones están bloqueadas hasta nuevo aviso.";
    cta = null;
  } else if (org.kyb_status === "in_review") {
    tone = "info";
    icon = <Clock size={16} />;
    title = "KYB en revisión";
    msg = "Tu información ya fue enviada y está siendo revisada por nuestro equipo de compliance. Te avisaremos por email — generalmente toma menos de 1 día hábil.";
    cta = null;
  } else if (org.kyb_status === "rejected") {
    tone = "danger";
    icon = <XCircle size={16} />;
    title = "KYB rechazado";
    msg = org.kyb_reject_reason
      ? `Motivo: ${org.kyb_reject_reason}. Contactanos para revisar el caso.`
      : "Nuestro equipo de compliance no pudo aprobar tu cuenta. Contactanos para más información.";
    cta = null;
  } else if (org.kyb_status === "needs_info") {
    tone = "warning";
    icon = <AlertTriangle size={16} />;
    title = "Necesitamos más información";
    msg = "Compliance solicitó documentación adicional. Reanudá el wizard para completar tu KYB.";
  }

  const styles = {
    warning: "bg-warning/10 border-warning/30 text-warning",
    info:    "bg-primary/10 border-primary/30 text-primary",
    danger:  "bg-danger/10 border-danger/30 text-danger",
  }[tone];

  return (
    <div
      className={`sticky top-0 z-30 border-b ${styles} backdrop-blur-sm`}
      data-testid="client-gate-banner"
      data-status={org.kyb_status}
    >
      <div className="mx-auto max-w-[1440px] px-6 py-2.5 flex items-center gap-3">
        <span className="shrink-0 inline-flex items-center justify-center h-7 w-7 rounded-full bg-bg/40">
          {icon}
        </span>
        <div className="flex-1 min-w-0">
          <div className="text-xs font-display font-semibold uppercase tracking-wide">
            {title}
          </div>
          <div className="text-xs text-fg-muted mt-0.5">{msg}</div>
        </div>
        {cta && (
          <Link
            href={cta.href}
            className="shrink-0 h-9 px-3 inline-flex items-center gap-1.5 rounded
                       bg-fg text-bg text-xs font-mono uppercase tracking-wider
                       hover:opacity-90 transition-opacity"
            data-testid="gate-banner-cta"
          >
            {cta.label}
            <ArrowRight size={12} />
          </Link>
        )}
      </div>
    </div>
  );
}
