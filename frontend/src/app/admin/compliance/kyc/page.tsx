"use client";
import { useMemo, useState } from "react";
import { PageHeader, Badge, DataTable, type Column } from "@prosper/ui";
import { Check, X, HelpCircle, ZoomIn } from "lucide-react";
import { toast } from "sonner";
import { useKycQueue, useKycCase, decideKyc, type KycCase, type KycDocument } from "@/lib/admin-compliance";
import { cn, fmtDate } from "@/lib/utils";

const SLA_TONE: Record<string, string> = {
  green: "text-success border-success/40 bg-success/10",
  amber: "text-warning border-warning/40 bg-warning/10",
  red:   "text-danger  border-danger/40  bg-danger/10",
};

export default function KycPage() {
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
        breadcrumbs={[{ label: "Admin", href: "/admin" },
                      { label: "Compliance", href: "/admin/compliance" },
                      { label: "KYC" }]}
        kicker="Phase 5 · Compliance"
        title="KYC · Personas físicas"
        subtitle="Cola de verificación de identidad con SLA visible y resoluciones registradas en audit log." />

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
  const [action, setAction] = useState<"approve" | "reject" | "request_info" | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [zoomDoc, setZoomDoc] = useState<KycDocument | null>(null);

  const submit = async () => {
    if (!action || reason.length < 20) {
      toast.error("Motivo mínimo 20 caracteres"); return;
    }
    setBusy(true);
    try {
      await decideKyc(caseId, { action, reason });
      toast.success(`KYC ${action} ok`);
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

            <Section title="Decisión">
              <div className="grid grid-cols-3 gap-2 mb-3">
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
              <textarea value={reason} onChange={(e) => setReason(e.target.value)}
                placeholder="Motivo (mínimo 20 caracteres)"
                rows={3}
                data-testid="kyc-reason"
                className="w-full px-3 py-2 rounded border border-border bg-surface
                           font-mono text-xs focus:outline-none focus:border-primary" />
              <div className="flex items-center justify-between mt-3">
                <span className="text-[10px] font-mono text-fg-subtle">{reason.length}/20+ chars</span>
                <button onClick={submit} disabled={!action || reason.length < 20 || busy}
                  data-testid="kyc-submit-decision"
                  className="prosper-btn-primary h-9 text-xs disabled:opacity-50">
                  {busy ? "Enviando…" : "Ejecutar decisión"}
                </button>
              </div>
            </Section>

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
