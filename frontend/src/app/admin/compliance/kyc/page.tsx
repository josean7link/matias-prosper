"use client";
import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { PageHeader, Badge, DataTable, type Column } from "@prosper/ui";
import { Check, X, HelpCircle, ZoomIn, ShieldCheck, AlertTriangle } from "lucide-react";
import { toast } from "sonner";
import { useKycQueue, useKycCase, decideKyc, type KycCase, type KycDocument } from "@/lib/admin-compliance";
import { useMe } from "@/lib/me";
import { cn, fmtDate } from "@/lib/utils";

const SLA_TONE: Record<string, string> = {
  green: "text-success border-success/40 bg-success/10",
  amber: "text-warning border-warning/40 bg-warning/10",
  red:   "text-danger  border-danger/40  bg-danger/10",
};

export default function KycPage() {
  const tH = useTranslations("admin.headers");
  const tA = useTranslations("admin");
  const [statusFilter, setStatusFilter] = useState<string[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const queue = useKycQueue({ status: statusFilter.length ? statusFilter : undefined });

  const cols: Column<KycCase>[] = [
    { key: "first_name", header: "Persona", sortable: true,
      render: (r) => (
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-full bg-primary/10 text-primary
                          flex items-center justify-center font-display font-bold text-[10px]">
            {(r.first_name?.[0] || "?") + (r.last_name?.[0] || "")}
          </div>
          <div>
            <div className="text-fg">{r.first_name} {r.last_name}</div>
            <div className="text-[10px] text-fg-subtle font-mono">{r.email}</div>
          </div>
        </div>) },
    { key: "org_id", header: "Org", width: "150px",
      render: (r) => r.org_id ? <Badge tone="auto" size="sm">{r.org_id.slice(0, 18)}</Badge>
                              : <span className="text-fg-subtle text-[10px]">—</span> },
    { key: "country", header: "País", width: "60px",
      render: (r) => <span className="font-mono text-[11px]">{r.country}</span> },
    { key: "applied_at", header: "Aplicado", width: "130px",
      render: (r) => <span className="font-mono text-[11px]">{fmtDate(r.applied_at)}</span> },
    { key: "provider", header: "Provider", width: "90px",
      render: (r) => <Badge tone="auto" size="sm">{r.provider}</Badge> },
    { key: "provider_score", header: "Score", numeric: true, sortable: true, width: "70px", align: "right",
      render: (r) => <span className="font-mono tabular">{r.provider_score}</span> },
    { key: "sla_hours_left", header: "SLA", width: "100px",
      render: (r) => (
        <span className={cn("font-mono text-[10px] px-2 py-0.5 rounded-full border",
                             SLA_TONE[r.sla_color || "green"])}
              data-testid={`sla-${r.case_id}`}>
          {r.sla_hours_left.toFixed(1)}h
        </span>) },
    { key: "status", header: "Status", width: "100px",
      render: (r) => <Badge size="sm"
        tone={r.status === "approved" ? "success" : r.status === "rejected" ? "danger" : "warning"}>
        {r.status}</Badge> },
  ];

  const STATUSES = ["pending", "in_review", "approved", "rejected", "needs_info"];

  return (
    <div data-testid="compl-kyc-page">
      <PageHeader
        breadcrumbs={[{ label: tA("breadcrumb_admin"), href: "/admin" },
                      { label: tH("comp_label"), href: "/admin/compliance" },
                      { label: tH("comp_kyc_bc") }]}
        kicker={tH("comp_kyc_kicker")}
        title={tH("comp_kyc_title")}
        subtitle={tH("comp_kyc_subtitle")} />

      <div className="flex flex-wrap items-center gap-1.5 mb-4" data-testid="kyc-filters">
        <span className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mr-1">Status</span>
        {STATUSES.map((s) => {
          const active = statusFilter.includes(s);
          return (
            <button key={s} onClick={() =>
              setStatusFilter((arr) => arr.includes(s) ? arr.filter((x) => x !== s) : [...arr, s])}
              data-testid={`kyc-chip-${s}`}
              className={cn("h-7 px-2.5 rounded-full text-[10px] font-mono uppercase tracking-wider",
                active ? "bg-fg text-bg"
                       : "bg-surface text-fg-muted hover:text-fg border border-border")}>
              {s}
            </button>
          );
        })}
      </div>

      <DataTable<KycCase>
        data={queue.data?.items ?? []} columns={cols}
        rowKey={(r) => r.case_id}
        onRowClick={(r) => setActiveId(r.case_id)}
        empty={queue.isLoading ? "Loading…" : "No KYC cases"} />

      {activeId && (
        <KycDrawer caseId={activeId}
          onClose={() => setActiveId(null)}
          onDecided={() => { queue.mutate(); setActiveId(null); }} />
      )}
    </div>
  );
}

function KycDrawer({ caseId, onClose, onDecided }:
  { caseId: string; onClose: () => void; onDecided: () => void }) {
  const swr = useKycCase(caseId);
  const c = swr.data;
  const meSwr = useMe();
  const myRole = meSwr.data?.user?.role;
  const canOverrideSanctions = myRole === "super_admin" || myRole === "finance";

  const [action, setAction] = useState<"approve" | "reject" | "request_info" | null>(null);
  const [reason, setReason] = useState("");
  const [overrideSanctions, setOverrideSanctions] = useState(false);
  const [overrideTravelRule, setOverrideTravelRule] = useState(false);
  const [busy, setBusy] = useState(false);
  const [zoomDoc, setZoomDoc] = useState<KycDocument | null>(null);

  // Manual overrides are offered only when:
  //   * case is an andes-direct application (status fields surfaced)
  //   * the corresponding screening is still pending
  //   * the current user has super_admin / finance role
  //   * the chosen action is "approve"
  const isAndesDirect = !!c?.case_id?.startsWith("app_");
  const sanctionsPending   = c?.sanctions_status   === "pending" && isAndesDirect;
  const travelRulePending  = c?.travel_rule_status === "pending" && isAndesDirect;
  const showSanctionsPanel  = sanctionsPending  && canOverrideSanctions && action === "approve";
  const showTravelRulePanel = travelRulePending && canOverrideSanctions && action === "approve";
  const anyOverrideApplied  = overrideSanctions || overrideTravelRule;

  const submit = async () => {
    if (!action || reason.length < 20) {
      toast.error("Motivo mínimo 20 caracteres"); return;
    }
    setBusy(true);
    try {
      const resp = await decideKyc(caseId, {
        action, reason,
        override_sanctions:    overrideSanctions   && action === "approve",
        override_travel_rule:  overrideTravelRule  && action === "approve",
      });
      const parts: string[] = [];
      if (resp.sanctions_override_applied)   parts.push("sanctions override");
      if (resp.travel_rule_override_applied) parts.push("travel-rule override");
      toast.success(parts.length
        ? `KYC aprobado + ${parts.join(" + ")} aplicado(s)`
        : `KYC ${action} ok`);
      onDecided();
    } catch (e: any) {
      toast.error(e?.message || "Decision failed");
    } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-40 flex" data-testid="kyc-drawer">
      <div className="flex-1 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="w-full max-w-[860px] bg-bg border-l border-border h-full overflow-y-auto p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">KYC case</div>
            <h2 className="font-display font-bold text-xl">{c ? `${c.first_name} ${c.last_name}` : "…"}</h2>
            {c && <div className="text-[11px] font-mono text-fg-subtle">
              {c.email} · {c.country} · doc {c.doc_id}</div>}
          </div>
          <button onClick={onClose} className="prosper-btn-ghost h-8 px-3 text-xs"
                  data-testid="kyc-drawer-close">Close</button>
        </div>

        {!c ? <div className="text-fg-subtle">Loading…</div> : (
          <div className="space-y-6">
            <Section title="Identidad · documentos">
              <div className="grid grid-cols-2 gap-3">
                {c.documents.map((d, i) => (
                  <button key={i} onClick={() => setZoomDoc(d)}
                    data-testid={`kyc-doc-${i}`}
                    className="relative group rounded border border-border overflow-hidden">
                    <img src={d.url} alt={d.label}
                         className="w-full h-32 object-cover bg-surface" />
                    <div className="absolute inset-0 bg-fg/40 opacity-0 group-hover:opacity-100
                                    transition-opacity flex items-center justify-center">
                      <ZoomIn size={20} className="text-white" />
                    </div>
                    <div className="absolute bottom-0 inset-x-0 bg-fg/80 text-bg px-2 py-1
                                    text-[10px] font-mono uppercase tracking-wider">
                      {d.label}
                    </div>
                  </button>
                ))}
              </div>
            </Section>

            <Section title="Provider result">
              <div className="grid grid-cols-3 gap-3">
                <Stat label="Score" value={String(c.provider_score)} />
                <Stat label="Confidence" value={`${(c.provider_confidence*100).toFixed(0)}%`} />
                <Stat label="Provider" value={c.provider} />
              </div>
              <div className="flex flex-wrap gap-1.5 mt-3">
                {c.provider_flags.map((f) => (
                  <Badge key={f} size="sm"
                    tone={f.includes("fail") || f.includes("alert") || f.includes("blurry")
                      ? "danger" : f.includes("pass") || f.includes("ok") ? "success" : "auto"}>
                    {f}</Badge>
                ))}
              </div>
            </Section>

            <Section title="Checks regulatorios">
              <div className="grid grid-cols-4 gap-2.5">
                {[["aml", "AML"], ["sanctions", "Sanctions"],
                  ["pep", "PEP"], ["travel_rule", "Travel rule"]].map(([k, lbl]) => {
                    const v = c.checks[k as keyof typeof c.checks];
                    const icon = v === "pass" ? <Check size={14}/> : v === "fail" ? <X size={14}/> : <HelpCircle size={14}/>;
                    const tone = v === "pass" ? "success" : v === "fail" ? "danger" : "warning";
                    return (
                      <div key={k} data-testid={`kyc-check-${k}`}
                        className="prosper-card p-3 text-center">
                        <div className="mx-auto mb-2 flex items-center justify-center">
                          <span className={cn(
                            "w-8 h-8 rounded-full flex items-center justify-center",
                            tone === "success" && "bg-success/15 text-success",
                            tone === "danger"  && "bg-danger/15 text-danger",
                            tone === "warning" && "bg-warning/15 text-warning",
                          )}>{icon}</span>
                        </div>
                        <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">{lbl}</div>
                        <div className="text-[11px] font-mono mt-0.5">{v}</div>
                      </div>
                    );
                })}
              </div>
            </Section>

            {/* When the case is in a terminal state, show a read-only summary
                instead of the decision panel. There's nothing left to decide
                here — overrides on sanctions / travel-rule still flow through
                their dedicated queues. */}
            {(c.status === "approved" || c.status === "rejected") ? (
              <Section title="Decisión">
                <div
                  className="rounded-lg border border-success/30 bg-success/5 p-4 flex items-start gap-3"
                  data-testid="kyc-already-decided"
                >
                  <Check size={18} className={cn("mt-0.5 shrink-0",
                    c.status === "approved" ? "text-success" : "text-danger")} />
                  <div className="flex-1 text-xs text-fg-muted">
                    <div className="font-display font-bold text-sm text-fg mb-1">
                      Caso {c.status === "approved" ? "aprobado" : "rechazado"}
                    </div>
                    Este caso ya está cerrado. Para revertir o reabrir, usá las
                    colas dedicadas{" "}
                    <a href="/admin/compliance/sanctions" className="text-primary hover:underline">
                      /admin/compliance/sanctions
                    </a>{" "}o{" "}
                    <a href="/admin/travel-rule" className="text-primary hover:underline">
                      /admin/travel-rule
                    </a>{" "}— una decisión `flagged` ahí vuelve a bloquear al
                    cliente automáticamente.
                  </div>
                </div>
              </Section>
            ) : (
            <Section title="Decisión">
              <div className="grid grid-cols-3 gap-2 mb-3" data-testid="kyc-action-pickers">
                {(["approve", "reject", "request_info"] as const).map((a) => (
                  <button key={a} onClick={() => setAction(a)}
                    data-testid={`kyc-action-${a}`}
                    className={cn("h-12 rounded-md font-mono uppercase text-[11px] tracking-wider border-2 transition-colors",
                      action === a
                        ? a === "approve" ? "bg-success text-white border-success"
                          : a === "reject" ? "bg-danger text-white border-danger"
                          : "bg-warning text-white border-warning"
                        : "border-border text-fg-muted hover:text-fg")}>
                    {a === "approve" ? "Aprobar" : a === "reject" ? "Rechazar" : "Solicitar info"}
                  </button>
                ))}
              </div>

              {/* ── Sanctions override panel (super_admin / finance only) ── */}
              {showSanctionsPanel && (
                <OverridePanel
                  kind="sanctions"
                  myRole={myRole}
                  checked={overrideSanctions}
                  onToggle={setOverrideSanctions}
                />
              )}

              {/* ── Travel-Rule override panel — same shape ── */}
              {showTravelRulePanel && (
                <OverridePanel
                  kind="travel_rule"
                  myRole={myRole}
                  checked={overrideTravelRule}
                  onToggle={setOverrideTravelRule}
                />
              )}

              {/* Hint when there are pending gates but the role can't override */}
              {(sanctionsPending || travelRulePending) && !canOverrideSanctions && action === "approve" && (
                <div
                  className="rounded-lg border border-fg-subtle/30 bg-surface p-3 mb-3 text-xs text-fg-muted"
                  data-testid="override-hint-blocked"
                >
                  {sanctionsPending && travelRulePending
                    ? "Sanctions y Travel-rule"
                    : sanctionsPending ? "Sanctions" : "Travel-rule"
                  }{" "}sigue <strong>pending</strong>. Solo super_admin o finance
                  pueden marcarlo como clear manualmente. Tu Aprobar marca{" "}
                  <strong>únicamente</strong> la identidad — el cliente queda
                  con identidad OK pero NO operativo hasta que alguien con
                  permiso resuelva los gates restantes.
                </div>
              )}

              <textarea value={reason} onChange={(e) => setReason(e.target.value)}
                placeholder="Motivo (mínimo 20 caracteres)"
                rows={3}
                data-testid="kyc-reason"
                className="w-full px-3 py-2 rounded border border-border bg-surface
                           font-mono text-xs focus:outline-none focus:border-primary" />
              <div className="flex items-center justify-between mt-3">
                <span className={cn("text-[10px] font-mono",
                  reason.length >= 20 ? "text-success" : "text-fg-subtle")}
                       data-testid="kyc-reason-counter">
                  {reason.length}/20+ chars
                </span>
                <button onClick={submit} disabled={!action || reason.length < 20 || busy}
                  data-testid="kyc-submit-decision"
                  className="prosper-btn-primary h-9 text-xs disabled:opacity-50">
                  {busy ? "Enviando…"
                    : action === "approve" && anyOverrideApplied
                      ? `Aprobar identidad${overrideSanctions ? " + sanctions" : ""}${overrideTravelRule ? " + travel-rule" : ""}`
                      : "Ejecutar decisión"}
                </button>
              </div>
            </Section>
            )}

            <Section title="Timeline">
              <ol className="border-l border-border pl-4 space-y-2.5">
                {c.timeline.map((t, i) => (
                  <li key={i} className="relative text-[11px] font-mono">
                    <span className="absolute -left-[18px] top-1 w-2 h-2 rounded-full bg-primary"/>
                    <span className="text-fg-subtle">{fmtDate(t.ts)}</span> ·
                    <span className="text-fg ml-1">{t.what}</span> ·
                    <span className="text-fg-subtle ml-1">{t.by}</span>
                  </li>
                ))}
              </ol>
            </Section>
          </div>
        )}

        {zoomDoc && (
          <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-8"
               onClick={() => setZoomDoc(null)} data-testid="kyc-zoom">
            <img src={zoomDoc.url} alt={zoomDoc.label}
                 className="max-w-full max-h-full rounded shadow-2xl" />
          </div>
        )}
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-2">{title}</h3>
      {children}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="prosper-card p-3">
      <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">{label}</div>
      <div className="text-fg font-display font-bold text-lg mt-0.5">{value}</div>
    </div>
  );
}

/**
 * OverridePanel — shared UI for sanctions and travel-rule manual override.
 * Both gates follow the exact same pattern (provider=manual today, super_admin
 * /finance can mark clear with audit-logged `resolution=manual_override`).
 */
function OverridePanel({ kind, myRole, checked, onToggle }:
  { kind: "sanctions" | "travel_rule"; myRole?: string;
    checked: boolean; onToggle: (v: boolean) => void }) {
  const isSanctions = kind === "sanctions";
  const label    = isSanctions ? "Sanctions / PEP" : "Travel Rule (FATF / UIF)";
  const cta      = isSanctions
    ? "También marcar sanctions/PEP como clear"
    : "También marcar travel-rule como clear";
  const providerHint = isSanctions
    ? "Si después se contrata ComplyAdvantage/Truora, el resultado real reemplaza este override automáticamente."
    : "Si después se contrata Notabene / Sumsub TR / TRP, el resultado real reemplaza este override automáticamente.";
  const testidPanel    = isSanctions ? "sanctions-override-panel"
                                       : "travel-rule-override-panel";
  const testidCheckbox = isSanctions ? "sanctions-override-checkbox"
                                       : "travel-rule-override-checkbox";

  return (
    <div
      className="rounded-lg border border-warning/40 bg-warning/5 p-4 mb-3"
      data-testid={testidPanel}
    >
      <div className="flex items-start gap-3">
        <AlertTriangle size={18} className="text-warning mt-0.5 shrink-0" />
        <div className="flex-1">
          <h4 className="font-display font-bold text-sm text-fg mb-1">
            {label} pendiente
          </h4>
          <p className="text-xs text-fg-muted leading-relaxed mb-3">
            No hay proveedor de {isSanctions ? "sanctions/PEP" : "travel-rule"} contratado
            todavía. Como{" "}
            <strong>{myRole === "super_admin" ? "super_admin" : "finance_admin"}</strong>{" "}
            podés marcar el screening como <strong>clear</strong> a mano
            para destrabar la operativa del cliente. Va a quedar registrado como{" "}
            <code className="font-mono bg-bg/60 px-1">resolution=manual_override</code>{" "}
            en el audit log, firmado con tu usuario. {providerHint}
          </p>
          <label className="flex items-start gap-2.5 cursor-pointer">
            <input
              type="checkbox"
              checked={checked}
              onChange={(e) => onToggle(e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-border accent-warning"
              data-testid={testidCheckbox}
            />
            <span className="text-xs text-fg">
              <strong>{cta}</strong> (override manual) — suma este gate al
              approve actual.
            </span>
          </label>
        </div>
      </div>
    </div>
  );
}
