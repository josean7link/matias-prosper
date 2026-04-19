import { useEffect, useState } from "react";
import api from "@/lib/api";
import { PageHeader, StatusBadge, EmptyState } from "@/components/common";
import { fmtDate, fmtNum, relativeTime } from "@/lib/format";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { toast } from "sonner";

export default function Onboarding() {
  const [items, setItems] = useState([]);
  const [status, setStatus] = useState("all");
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);

  const load = async () => {
    const params = new URLSearchParams();
    if (status !== "all") params.set("status", status);
    const { data } = await api.get(`/onboarding?${params}`);
    setItems(data.items || []);
  };

  useEffect(() => { load(); }, [status]);

  const openCase = async (c) => {
    setSelected(c);
    const { data } = await api.get(`/onboarding/${c.case_id}`);
    setDetail(data);
  };

  const action = async (decision) => {
    if (!detail?.compliance?.review_id) {
      await api.patch(`/onboarding/${selected.case_id}`, { status: decision, progress: 100 });
    } else {
      await api.post(`/compliance/${detail.compliance.review_id}/decide`, { decision });
    }
    toast.success(`Case ${decision}`);
    setSelected(null); setDetail(null);
    load();
  };

  return (
    <div data-testid="onboarding-page">
      <PageHeader title="Onboarding Queue" subtitle={`${items.length} applications`} />
      <div className="mb-4 flex gap-3">
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger className="w-[200px] bg-[var(--surface)] border-[var(--border)] rounded-md" data-testid="onboarding-filter">
            <SelectValue placeholder="Status" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            <SelectItem value="submitted">Submitted</SelectItem>
            <SelectItem value="under_review">Under Review</SelectItem>
            <SelectItem value="needs_info">Needs Info</SelectItem>
            <SelectItem value="approved">Approved</SelectItem>
            <SelectItem value="rejected">Rejected</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {items.length === 0 ? <EmptyState title="No cases in this view" /> : (
        <div className="prosper-card overflow-hidden">
          <table className="data-table w-full">
            <thead><tr>
              <th className="text-left px-4 py-3">Applicant</th>
              <th className="text-left px-4 py-3">Type</th>
              <th className="text-left px-4 py-3">Country</th>
              <th className="text-right px-4 py-3">Risk</th>
              <th className="text-right px-4 py-3">Progress</th>
              <th className="text-left px-4 py-3">Status</th>
              <th className="text-left px-4 py-3">SLA</th>
            </tr></thead>
            <tbody>
              {items.map((c) => (
                <tr key={c.case_id} className="cursor-pointer" onClick={() => openCase(c)} data-testid={`onboarding-row-${c.case_id}`}>
                  <td className="px-4 py-3 text-[var(--fg)]">{c.applicant_name}<div className="text-[11px] text-[var(--fg-subtle)] font-mono">{c.applicant_email}</div></td>
                  <td className="px-4 py-3 text-[var(--fg)] capitalize">{c.applicant_type}</td>
                  <td className="px-4 py-3 font-mono text-[var(--fg-muted)]">{c.country || "—"}</td>
                  <td className="px-4 py-3 text-right font-mono">{c.risk_score ? fmtNum(c.risk_score * 100, 0) + "%" : "—"}</td>
                  <td className="px-4 py-3 text-right">
                    <div className="inline-flex items-center gap-2">
                      <div className="w-16 h-1 bg-[var(--border)] rounded-full overflow-hidden">
                        <div className="h-full bg-[#0066FF]" style={{ width: `${c.progress || 0}%` }} />
                      </div>
                      <span className="font-mono text-xs">{c.progress || 0}%</span>
                    </div>
                  </td>
                  <td className="px-4 py-3"><StatusBadge value={c.status} /></td>
                  <td className="px-4 py-3 text-xs font-mono text-[var(--fg-muted)]">{relativeTime(c.sla_due)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Dialog open={!!selected} onOpenChange={(o) => !o && setSelected(null)}>
        <DialogContent className="max-w-2xl bg-[var(--surface)] border-[var(--border-strong)]">
          <DialogHeader><DialogTitle className="font-display">{selected?.applicant_name}</DialogTitle></DialogHeader>
          {detail && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4 text-sm">
                <Field label="Email" value={selected.applicant_email} />
                <Field label="Country" value={selected.country} />
                <Field label="Type" value={selected.applicant_type} />
                <Field label="Status"><StatusBadge value={selected.status} /></Field>
                <Field label="Risk" value={selected.risk_score ? (selected.risk_score * 100).toFixed(0) + "%" : "—"} />
                <Field label="Created" value={fmtDate(selected.created_at, true)} />
              </div>
              <div className="border-t border-[var(--border)] pt-4">
                <div className="text-[10px] uppercase tracking-wider text-[var(--fg-muted)] mb-2">Compliance Checks</div>
                <div className="grid grid-cols-2 gap-y-2 text-xs">
                  <div><span className="text-[var(--fg-muted)]">KYC:</span> <StatusBadge value={detail.compliance?.kyc_status} /></div>
                  <div><span className="text-[var(--fg-muted)]">AML:</span> <StatusBadge value={detail.compliance?.aml_check} /></div>
                  <div><span className="text-[var(--fg-muted)]">Sanctions:</span> <StatusBadge value={detail.compliance?.sanctions_check} /></div>
                  <div><span className="text-[var(--fg-muted)]">PEP:</span> <StatusBadge value={detail.compliance?.pep_check} /></div>
                  <div><span className="text-[var(--fg-muted)]">Travel Rule:</span> <StatusBadge value={detail.compliance?.travel_rule} /></div>
                  <div><span className="text-[var(--fg-muted)]">Decision:</span> <StatusBadge value={detail.compliance?.decision} /></div>
                </div>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => action("rejected")} data-testid="case-reject"
                    className="border-[#FF3D00]/40 text-[var(--danger)] hover:bg-[#FF3D00]/10 rounded-sm">Reject</Button>
            <Button variant="outline" onClick={() => action("needs_info")} data-testid="case-needs-info"
                    className="border-[#FFAB00]/40 text-[var(--warning)] hover:bg-[#FFAB00]/10 rounded-sm">Request Info</Button>
            <Button onClick={() => action("approved")} data-testid="case-approve"
                    className="bg-[#00C853] text-black hover:bg-[#00B84A] rounded-sm font-semibold">Approve</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

const Field = ({ label, value, children }) => (
  <div>
    <div className="text-[10px] uppercase tracking-wider text-[var(--fg-muted)]">{label}</div>
    <div className="mt-0.5 text-[var(--fg)]">{children || value || "—"}</div>
  </div>
);
