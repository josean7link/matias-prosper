"use client";
import { useState } from "react";
import { PageHeader, Badge, DataTable, type Column } from "@prosper/ui";
import { toast } from "sonner";
import { RefreshCw, CheckCircle2, XCircle, Clock, ExternalLink } from "lucide-react";
import {
  useComplianceSummary, useApplications, useKycCases,
  decideApplication, decideKyc,
  type OnboardingApplication, type KycCase,
} from "@/lib/compliance";
import { cn, fmtDate } from "@/lib/utils";

type Tab = "kyb" | "kyc";

export default function Page() {
  const [tab, setTab] = useState<Tab>("kyb");
  const summary = useComplianceSummary();

  const refresh = () => { summary.mutate(); };

  return (
    <div data-testid="compliance-page">
      <PageHeader
        breadcrumbs={[{ label: "Admin", href: "/admin" }, { label: "Compliance" }]}
        kicker="Phase 3 · Onboarding"
        title="Compliance"
        subtitle="Onboarding applications (KYB) and identity verification (KYC) cases."
        actions={
          <button onClick={refresh}
            className="prosper-btn-ghost h-9 text-xs gap-1.5"
            data-testid="compliance-refresh">
            <RefreshCw size={13} /> Refresh
          </button>
        }
      />

      {/* Summary tiles */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <Stat label="KYB · pending" value={summary.data?.kyb.pending} tone="warning"
              testid="stat-kyb-pending" />
        <Stat label="KYB · approved" value={summary.data?.kyb.approved} tone="success"
              testid="stat-kyb-approved" />
        <Stat label="KYB · rejected" value={summary.data?.kyb.rejected} tone="danger"
              testid="stat-kyb-rejected" />
        <Stat label="KYC · pending" value={summary.data?.kyc.pending} tone="primary"
              testid="stat-kyc-pending" />
      </div>

      {/* Tabs */}
      <div className="inline-flex items-center bg-surface border border-border
                      rounded p-0.5 text-[11px] font-mono uppercase tracking-wider mb-4"
           role="tablist" data-testid="compliance-tabs">
        {(["kyb", "kyc"] as const).map((t) => (
          <button key={t} role="tab" aria-selected={t === tab}
            onClick={() => setTab(t)}
            data-testid={`compliance-tab-${t}`}
            className={cn(
              "px-3 h-8 rounded transition-colors",
              t === tab ? "bg-fg text-bg" : "text-fg-subtle hover:text-fg",
            )}>
            {t === "kyb" ? "Business · KYB" : "Identity · KYC"}
          </button>
        ))}
      </div>

      {tab === "kyb" ? <KybTab /> : <KycTab />}
    </div>
  );
}

/* ──────────────────── KYB tab ──────────────────── */
function KybTab() {
  const apps = useApplications();
  const [open, setOpen] = useState<OnboardingApplication | null>(null);

  const cols: Column<OnboardingApplication>[] = [
    {
      key: "legal_name", header: "Organization", sortable: true,
      render: (r) => (
        <div className="min-w-0">
          <div className="text-fg truncate">{r.legal_name}</div>
          <div className="text-[10px] font-mono text-fg-subtle">{r.org_id}</div>
        </div>
      ),
    },
    { key: "country", header: "Country", width: "80px" },
    {
      key: "submitted_at", header: "Submitted", width: "140px",
      sortable: true, render: (r) => (
        <span className="font-mono text-[11px]">{fmtDate(r.submitted_at)}</span>
      ),
    },
    {
      key: "kyb_status", header: "KYB", width: "130px",
      render: (r) => (
        <div className="flex items-center gap-1.5">
          <Badge tone="auto" size="sm">{r.kyb_status}</Badge>
          {r.aiprise_mode === "simulated" && (
            <span className="text-[9px] font-mono uppercase tracking-wider
                              text-warning bg-warning/10 px-1 rounded">sim</span>
          )}
        </div>
      ),
    },
    {
      key: "status", header: "Status", width: "120px",
      render: (r) => <Badge tone="auto" size="sm">{r.status}</Badge>,
    },
    {
      key: "application_id", header: "", width: "80px", align: "right",
      render: (r) => (
        <button onClick={() => setOpen(r)}
          data-testid={`kyb-open-${r.application_id}`}
          className="text-[10px] font-mono uppercase tracking-wider
                     text-primary hover:underline">
          Review →
        </button>
      ),
    },
  ];

  return (
    <>
      <DataTable<OnboardingApplication>
        data={apps.data?.items ?? []} columns={cols}
        rowKey={(r) => r.application_id}
        empty={apps.isLoading ? "Loading…" : "No applications yet"} />
      {open && <KybReviewModal app={open} onClose={() => { setOpen(null); apps.mutate(); }} />}
    </>
  );
}

function KybReviewModal({ app, onClose }:
  { app: OnboardingApplication; onClose: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const decide = async (decision: "approved" | "rejected" | "needs_info") => {
    setBusy(decision);
    try {
      await decideApplication(app.application_id, decision, note || undefined);
      toast.success(`Application ${decision}`);
      onClose();
    } catch (err: any) {
      toast.error(err?.message || "Decision failed");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center
                    bg-black/50 backdrop-blur-sm p-4"
         onClick={onClose} data-testid="kyb-modal">
      <div onClick={(e) => e.stopPropagation()}
           className="prosper-card w-full max-w-lg p-6 max-h-[90vh] overflow-auto">
        <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
          KYB review · {app.application_id}
        </div>
        <h2 className="font-display font-bold text-xl text-fg mt-1">
          {app.legal_name}
        </h2>
        <div className="mt-1 flex items-center gap-2">
          <Badge tone="auto" size="sm">{app.kyb_status}</Badge>
          {app.aiprise_mode === "simulated" && (
            <span className="text-[10px] font-mono uppercase tracking-wider
                              text-warning bg-warning/10 px-1.5 py-0.5 rounded">
              AiPrise · simulated
            </span>
          )}
        </div>

        <dl className="mt-4 grid grid-cols-2 gap-3 text-xs">
          <Cell label="Country">{app.country}</Cell>
          <Cell label="Jurisdiction">{app.jurisdiction}</Cell>
          <Cell label="Submitted">{fmtDate(app.submitted_at)}</Cell>
          <Cell label="Expected vol/mo">
            {app.expected_monthly_volume_usd
              ? `$${Number(app.expected_monthly_volume_usd).toLocaleString()}` : "—"}
          </Cell>
          <Cell label="Contact" full>
            {app.contact_name} · <span className="font-mono">{app.contact_email}</span>
          </Cell>
          {app.use_case && <Cell label="Use case" full>{app.use_case}</Cell>}
        </dl>

        {app.ubos && app.ubos.length > 0 && (
          <div className="mt-4">
            <div className="text-[10px] font-mono uppercase tracking-[0.15em]
                            text-fg-subtle mb-1">UBOs</div>
            <ul className="space-y-1">
              {app.ubos.map((u, i) => (
                <li key={i} className="text-xs font-mono text-fg-muted flex
                                       items-center justify-between border-b
                                       border-border py-1">
                  <span>{u.full_name} {u.role && `· ${u.role}`}</span>
                  <span className="tabular">{u.ownership_pct}%</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {app.aiprise_session_id && (
          <div className="mt-4 text-[10px] font-mono text-fg-subtle">
            session · {app.aiprise_session_id}
          </div>
        )}

        <textarea value={note} onChange={(e) => setNote(e.target.value)}
          placeholder="Decision note (optional)"
          data-testid="kyb-note"
          className="prosper-input mt-4 w-full text-xs min-h-[60px]" />

        <div className="mt-4 grid grid-cols-3 gap-2">
          <button onClick={() => decide("rejected")}
            disabled={busy !== null}
            data-testid="kyb-decision-rejected"
            className="h-10 rounded text-xs font-medium bg-danger text-white
                       hover:bg-danger/90 disabled:opacity-50 flex items-center
                       justify-center gap-1">
            <XCircle size={13} /> Reject
          </button>
          <button onClick={() => decide("needs_info")}
            disabled={busy !== null}
            data-testid="kyb-decision-needs-info"
            className="h-10 rounded text-xs font-medium bg-warning text-white
                       hover:bg-warning/90 disabled:opacity-50 flex items-center
                       justify-center gap-1">
            <Clock size={13} /> Needs info
          </button>
          <button onClick={() => decide("approved")}
            disabled={busy !== null}
            data-testid="kyb-decision-approved"
            className="h-10 rounded text-xs font-medium bg-success text-white
                       hover:bg-success/90 disabled:opacity-50 flex items-center
                       justify-center gap-1">
            <CheckCircle2 size={13} /> Approve
          </button>
        </div>

        <button onClick={onClose}
          className="mt-3 text-[10px] font-mono uppercase tracking-wider
                     text-fg-subtle hover:text-fg w-full">
          Close
        </button>
      </div>
    </div>
  );
}

/* ──────────────────── KYC tab ──────────────────── */
function KycTab() {
  const cases = useKycCases();
  const cols: Column<KycCase>[] = [
    {
      key: "email", header: "User", sortable: true,
      render: (r) => (
        <div className="min-w-0">
          <div className="text-fg font-mono text-xs truncate">{r.email}</div>
          <div className="text-[10px] font-mono text-fg-subtle">{r.user_id}</div>
        </div>
      ),
    },
    { key: "role", header: "Role", width: "120px",
      render: (r) => <Badge tone="auto" size="sm">{r.role}</Badge> },
    { key: "org_id", header: "Org", width: "180px",
      render: (r) => <span className="font-mono text-[11px]">{r.org_id ?? "—"}</span> },
    {
      key: "kyc_status", header: "KYC", width: "120px",
      render: (r) => (
        <div className="flex items-center gap-1.5">
          <Badge tone="auto" size="sm">{r.kyc_status}</Badge>
          {r.kyc_mode === "simulated" && (
            <span className="text-[9px] font-mono uppercase tracking-wider
                              text-warning bg-warning/10 px-1 rounded">sim</span>
          )}
        </div>
      ),
    },
    {
      key: "updated_at", header: "Updated", width: "140px",
      render: (r) => <span className="font-mono text-[11px]">{fmtDate(r.updated_at)}</span>,
    },
    {
      key: "user_id", header: "", width: "180px", align: "right",
      render: (r) => <KycInlineActions row={r} />,
    },
  ];
  return (
    <DataTable<KycCase>
      data={cases.data?.items ?? []} columns={cols}
      rowKey={(r) => r.user_id}
      empty={cases.isLoading ? "Loading…" : "No KYC cases pending"} />
  );
}

function KycInlineActions({ row }: { row: KycCase }) {
  const [busy, setBusy] = useState<string | null>(null);
  const cases = useKycCases();
  const decide = async (decision: "approved" | "rejected") => {
    setBusy(decision);
    try {
      await decideKyc(row.user_id, decision);
      toast.success(`KYC ${decision}`);
      cases.mutate();
    } catch (err: any) {
      toast.error(err?.message || "Decision failed");
    } finally { setBusy(null); }
  };
  return (
    <div className="inline-flex gap-1">
      <button onClick={() => decide("rejected")} disabled={busy !== null}
        data-testid={`kyc-reject-${row.user_id}`}
        className="text-[10px] font-mono uppercase tracking-wider
                   text-danger hover:bg-danger/10 px-2 h-7 rounded
                   disabled:opacity-50">Reject</button>
      <button onClick={() => decide("approved")} disabled={busy !== null}
        data-testid={`kyc-approve-${row.user_id}`}
        className="text-[10px] font-mono uppercase tracking-wider
                   text-success hover:bg-success/10 px-2 h-7 rounded
                   disabled:opacity-50">Approve</button>
    </div>
  );
}

/* ──────────────────── small helpers ──────────────────── */
function Stat({ label, value, tone, testid }:
  { label: string; value: number | undefined; tone: string; testid: string }) {
  return (
    <div className="prosper-card p-4" data-testid={testid}>
      <div className="text-[10px] uppercase tracking-[0.15em] font-mono text-fg-subtle">
        {label}
      </div>
      <div className={cn("font-display font-extrabold text-2xl text-fg
                          tabular mt-1 leading-tight font-mono",
                          tone === "danger" && "text-danger",
                          tone === "warning" && "text-warning",
                          tone === "success" && "text-success")}>
        {value ?? "—"}
      </div>
    </div>
  );
}

function Cell({ label, children, full }:
  { label: string; children: React.ReactNode; full?: boolean }) {
  return (
    <div className={full ? "col-span-2" : ""}>
      <dt className="text-[10px] font-mono uppercase tracking-[0.15em]
                     text-fg-subtle">{label}</dt>
      <dd className="text-fg">{children}</dd>
    </div>
  );
}
