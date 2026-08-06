"use client";
import { useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import {
  ShieldX, ShieldCheck, Clock, CheckCircle2, XCircle, Loader2, RefreshCw,
} from "lucide-react";
import { api } from "@/lib/api";
import { Badge } from "@prosper/ui";

interface Screening {
  screening_id: string;
  org_id: string;
  subject_type: "individual" | "business";
  subject_name: string;
  subject_cuit?: string | null;
  subject_birthdate?: string | null;
  country: string;
  status: "pending" | "clear" | "flagged";
  reason?: string | null;
  provider: string;
  decided_by?: string | null;
  decided_at?: string | null;
  created_at: string;
  organization?: {
    legal_name: string; country: string; kyb_status: string; type: string;
    sanctions_status: string;
  } | null;
}

type Tab = "pending" | "clear" | "flagged";

const TAB_KEY: Record<Tab, "sanctions_tab_pending" | "sanctions_tab_clear" | "sanctions_tab_flagged"> = {
  pending: "sanctions_tab_pending",
  clear:   "sanctions_tab_clear",
  flagged: "sanctions_tab_flagged",
};
const TAB_ICON: Record<Tab, React.ReactNode> = {
  pending: <Clock size={13}/>,
  clear:   <CheckCircle2 size={13}/>,
  flagged: <XCircle size={13}/>,
};

export default function SanctionsQueuePage() {
  const tH = useTranslations("admin.headers");
  const [tab, setTab] = useState<Tab>("pending");
  const { data, isLoading, mutate } =
    useSWR<{ items: Screening[]; count: number }>(
      `/v1/admin/sanctions/queue?status=${tab}`,
      (p: string) => api(p),
      { refreshInterval: 15_000 },
    );
  const [active, setActive] = useState<Screening | null>(null);

  return (
    <div data-testid="sanctions-page">
      <header className="mb-5 flex items-end justify-between gap-3">
        <div>
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-1">
            {tH("sanctions_kicker")}
          </div>
          <h1 className="font-display font-bold text-3xl text-fg flex items-center gap-2">
            <ShieldX size={22} className="text-primary"/> {tH("sanctions_title")}
          </h1>
        </div>
        <button
          onClick={() => mutate()}
          className="prosper-btn-ghost h-9 px-3 text-xs gap-1.5 border border-border"
          data-testid="sanctions-refresh"
        >
          <RefreshCw size={12}/> {tH("sanctions_refresh")}
        </button>
      </header>

      <div className="inline-flex bg-surface rounded-lg border border-border p-1 mb-5"
           data-testid="sanctions-tabs">
        {(Object.keys(TAB_KEY) as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            data-testid={`sanctions-tab-${t}`}
            className={`h-9 px-4 text-xs font-display font-semibold rounded-md
                        inline-flex items-center gap-2 transition-colors
                        ${tab === t
                          ? "bg-primary text-white shadow-card"
                          : "text-fg-muted hover:text-fg"}`}
          >
            {TAB_ICON[t]} {tH(TAB_KEY[t])}
          </button>
        ))}
      </div>

      <div className="prosper-card overflow-hidden" data-testid="sanctions-table">
        <table className="w-full text-sm">
          <thead className="bg-surface text-[10px] font-mono uppercase tracking-wider
                              text-fg-subtle border-b border-border">
            <tr>
              <th className="text-left px-4 py-2.5">Cliente</th>
              <th className="text-left px-4 py-2.5">Tipo</th>
              <th className="text-left px-4 py-2.5">CUIT</th>
              <th className="text-left px-4 py-2.5">País</th>
              <th className="text-left px-4 py-2.5">KYB</th>
              <th className="text-left px-4 py-2.5">Status</th>
              <th className="text-left px-4 py-2.5">Encolado</th>
              <th className="text-right px-4 py-2.5">Acción</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr><td colSpan={8} className="text-center py-10">
                <Loader2 size={18} className="inline animate-spin text-fg-subtle"/>
              </td></tr>
            )}
            {!isLoading && (data?.items.length ?? 0) === 0 && (
              <tr><td colSpan={8} className="text-center text-fg-subtle py-10 text-xs"
                     data-testid="sanctions-empty">
                Sin casos en estado {TAB_LABEL[tab].toLowerCase()}.
              </td></tr>
            )}
            {data?.items.map((s) => (
              <tr key={s.screening_id}
                  className="border-b border-border last:border-b-0 hover:bg-surface-hover"
                  data-testid={`sanctions-row-${s.org_id}`}>
                <td className="px-4 py-3 font-display font-semibold text-fg">
                  {s.subject_name}
                  <div className="text-[10px] font-mono text-fg-subtle">{s.org_id}</div>
                </td>
                <td className="px-4 py-3 text-xs uppercase tracking-wider text-fg-muted">
                  {s.subject_type}
                </td>
                <td className="px-4 py-3 font-mono text-xs">{s.subject_cuit || "—"}</td>
                <td className="px-4 py-3 text-xs">{s.country}</td>
                <td className="px-4 py-3">
                  <Badge tone="auto" size="sm">
                    {s.organization?.kyb_status || "—"}
                  </Badge>
                </td>
                <td className="px-4 py-3">
                  <StatusBadge status={s.status}/>
                </td>
                <td className="px-4 py-3 text-[11px] font-mono text-fg-subtle">
                  {new Date(s.created_at).toLocaleString("es-AR")}
                </td>
                <td className="px-4 py-3 text-right">
                  {s.status === "pending" ? (
                    <button
                      onClick={() => setActive(s)}
                      data-testid={`sanctions-review-${s.org_id}`}
                      className="prosper-btn-primary h-8 px-3 text-[11px]">
                      Revisar
                    </button>
                  ) : (
                    <button
                      onClick={() => setActive(s)}
                      className="text-[11px] text-fg-subtle hover:text-fg font-mono uppercase tracking-wider"
                      data-testid={`sanctions-detail-${s.org_id}`}>
                      Detalle
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {active && (
        <DecisionModal
          screening={active}
          onClose={() => setActive(null)}
          onDecided={() => { setActive(null); mutate(); toast.success("Decisión registrada"); }}
        />
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: "pending" | "clear" | "flagged" }) {
  const map = {
    pending: { tone: "warning" as const, label: "Pending" },
    clear:   { tone: "success" as const, label: "Clear"   },
    flagged: { tone: "danger"  as const, label: "Flagged" },
  };
  const m = map[status];
  return <Badge tone={m.tone} size="sm">{m.label}</Badge>;
}

function DecisionModal({ screening, onClose, onDecided }:
  { screening: Screening; onClose: () => void; onDecided: () => void }) {
  const [decision, setDecision] = useState<"clear" | "flagged" | null>(null);
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const isHistorical = screening.status !== "pending";

  const submit = async () => {
    if (!decision || reason.trim().length < 2) {
      toast.error("Seleccioná una decisión y agregá un motivo (mín. 2 caracteres).");
      return;
    }
    setSubmitting(true);
    try {
      await api(`/v1/admin/sanctions/${screening.org_id}/decision`, {
        method: "POST",
        body: JSON.stringify({ decision, reason: reason.trim() }),
      });
      onDecided();
    } catch (e) {
      const err = e as Error;
      toast.error(err.message || "No se pudo registrar la decisión");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-bg/70 backdrop-blur-sm
                     flex items-center justify-center p-4"
         onClick={onClose}
         data-testid="sanctions-modal">
      <div className="prosper-card max-w-lg w-full p-6"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3 mb-4">
          <div>
            <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
              Screening · {screening.subject_type}
            </div>
            <h2 className="font-display font-bold text-lg text-fg mt-0.5">
              {screening.subject_name}
            </h2>
          </div>
          <button onClick={onClose} className="text-fg-subtle hover:text-fg text-lg"
                  data-testid="sanctions-modal-close">×</button>
        </div>

        <dl className="grid grid-cols-2 gap-3 mb-5 text-xs">
          <Info k="CUIT"        v={screening.subject_cuit || "—"} mono/>
          <Info k="Nacimiento"  v={screening.subject_birthdate || "—"} mono/>
          <Info k="País"        v={screening.country}/>
          <Info k="Org ID"      v={screening.org_id} mono/>
          <Info k="KYB actual"  v={screening.organization?.kyb_status || "—"}/>
          <Info k="Proveedor"   v={screening.provider}/>
        </dl>

        {isHistorical ? (
          <div className="bg-surface rounded-lg p-4 text-xs"
               data-testid="sanctions-history">
            <div className="flex items-center gap-2 mb-2">
              <StatusBadge status={screening.status}/>
              <span className="text-fg-subtle font-mono text-[10px] uppercase tracking-wider">
                {screening.decided_by} · {screening.decided_at
                  ? new Date(screening.decided_at).toLocaleString("es-AR") : "—"}
              </span>
            </div>
            <p className="text-fg-muted">{screening.reason}</p>
          </div>
        ) : (
          <>
            <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-2">
              Decisión
            </div>
            <div className="flex gap-2 mb-4" data-testid="sanctions-decision-options">
              <button
                onClick={() => setDecision("clear")}
                data-testid="sanctions-pick-clear"
                className={`flex-1 h-12 rounded-lg border text-sm font-display font-semibold
                            inline-flex items-center justify-center gap-2 transition-colors
                            ${decision === "clear"
                              ? "bg-success text-white border-success"
                              : "bg-surface border-border text-fg-muted hover:text-fg"}`}>
                <ShieldCheck size={15}/> Clear · sin matches
              </button>
              <button
                onClick={() => setDecision("flagged")}
                data-testid="sanctions-pick-flagged"
                className={`flex-1 h-12 rounded-lg border text-sm font-display font-semibold
                            inline-flex items-center justify-center gap-2 transition-colors
                            ${decision === "flagged"
                              ? "bg-danger text-white border-danger"
                              : "bg-surface border-border text-fg-muted hover:text-fg"}`}>
                <ShieldX size={15}/> Flagged · bloquear
              </button>
            </div>

            <label className="block mb-4">
              <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-1">
                Motivo / referencia *
              </div>
              <textarea
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                rows={3}
                placeholder="Ej.: Sin matches en OFAC / UN / PEP / Worldcheck (referencia: ticket OPS-1234)"
                className="prosper-input w-full text-sm"
                data-testid="sanctions-reason"
              />
              <p className="text-[10px] text-fg-subtle mt-1">
                Queda registrado en audit_logs. Cuando contratemos un proveedor
                real, este motivo lo va a generar el proveedor.
              </p>
            </label>

            <div className="flex items-center justify-between">
              <button onClick={onClose}
                      className="text-xs font-mono uppercase tracking-wider text-fg-subtle
                                  hover:text-fg">Cancelar</button>
              <button
                onClick={submit}
                disabled={submitting || !decision || reason.trim().length < 2}
                data-testid="sanctions-submit"
                className="prosper-btn-primary h-10 px-5 text-sm disabled:opacity-40">
                {submitting ? "Registrando…" : "Registrar decisión"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Info({ k, v, mono }: { k: string; v: string; mono?: boolean }) {
  return (
    <div>
      <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">{k}</div>
      <div className={mono ? "font-mono text-xs text-fg" : "text-xs text-fg"}>{v}</div>
    </div>
  );
}
