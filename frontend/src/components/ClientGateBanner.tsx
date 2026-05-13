"use client";
import Link from "next/link";
import { AlertTriangle, Clock, XCircle, PauseCircle, ArrowRight, CheckCircle2 } from "lucide-react";
import { useClientMe } from "@/lib/client-portal";

/**
 * Sticky onboarding/gate banner for the Client portal.
 * Shown when `kyb_status != approved` OR `paused == true`.
 * Includes a slim progress bar derived from the latest KybCase checklist.
 */
export function ClientGateBanner() {
  const { data } = useClientMe();
  if (!data) return null;
  const org = data.org;
  const onb = data.onboarding;
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
    msg = "Tu información fue enviada y compliance la está revisando. Te avisamos por email — generalmente toma menos de 1 día hábil.";
    cta = null;
  } else if (org.kyb_status === "rejected") {
    tone = "danger";
    icon = <XCircle size={16} />;
    title = "KYB rechazado";
    msg = org.kyb_reject_reason
      ? `Motivo: ${org.kyb_reject_reason}. Contactanos para revisar el caso.`
      : "Compliance no pudo aprobar tu cuenta. Escribinos para más información.";
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

  const trackBg = {
    warning: "bg-warning/20",
    info:    "bg-primary/20",
    danger:  "bg-danger/20",
  }[tone];

  const barBg = {
    warning: "bg-warning",
    info:    "bg-primary",
    danger:  "bg-danger",
  }[tone];

  // Build progress chips
  const chips: Array<{ key: string; label: string; done: boolean }> = [
    {
      key: "applied",
      label: "Wizard enviado",
      done: onb.has_case || ["in_review", "needs_info", "approved", "rejected"].includes(org.kyb_status),
    },
    {
      key: "review",
      label: `Checklist ${onb.checklist_done}/${onb.checklist_total}`,
      done: onb.checklist_done >= onb.checklist_total,
    },
    {
      key: "approval",
      label: "Aprobación",
      done: org.kyb_status === "approved",
    },
  ];

  return (
    <div
      className={`sticky top-0 z-30 border-b ${styles} backdrop-blur-sm`}
      data-testid="client-gate-banner"
      data-status={org.kyb_status}
    >
      <div className="mx-auto max-w-[1440px] px-6 py-2.5">
        <div className="flex items-center gap-3">
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

        {/* Progress strip — hidden when paused or rejected (no progress to show) */}
        {!paused && org.kyb_status !== "rejected" && (
          <div className="mt-2 flex items-center gap-3" data-testid="gate-banner-progress">
            <div className="flex-1 flex items-center gap-2 min-w-0">
              <div className={`relative h-1.5 flex-1 rounded-full overflow-hidden ${trackBg}`}>
                <div
                  className={`absolute inset-y-0 left-0 ${barBg} rounded-full transition-all duration-500`}
                  style={{ width: `${Math.max(4, onb.percent)}%` }}
                  data-testid="gate-progress-bar"
                  data-percent={onb.percent}
                />
              </div>
              <span
                className="text-[10px] font-mono tabular-nums shrink-0 opacity-80"
                data-testid="gate-progress-pct"
              >
                {onb.percent}%
              </span>
            </div>
            <ul className="hidden md:flex items-center gap-3 text-[10px] font-mono uppercase tracking-wider">
              {chips.map((c) => (
                <li
                  key={c.key}
                  className={`inline-flex items-center gap-1 ${c.done ? "opacity-100" : "opacity-50"}`}
                  data-testid={`gate-chip-${c.key}`}
                  data-done={c.done}
                >
                  {c.done ? (
                    <CheckCircle2 size={11} />
                  ) : (
                    <span className="h-2.5 w-2.5 rounded-full border border-current" />
                  )}
                  {c.label}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
