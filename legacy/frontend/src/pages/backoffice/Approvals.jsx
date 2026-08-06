import { useEffect, useState } from "react";
import api from "@/lib/api";
import { useApp } from "@/contexts/AppContext";
import { PageHeader, StatusBadge, EmptyState } from "@/components/common";
import { fmtMoney, fmtDateTime, relativeTime } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { ShieldCheck, XCircle, Clock, CheckCircle } from "@phosphor-icons/react";

const STATUS_FILTERS = [
  { value: "all", label: "All" },
  { value: "pending", label: "Pending" },
  { value: "executed", label: "Executed" },
  { value: "rejected", label: "Rejected" },
  { value: "failed", label: "Failed" },
];

export default function Approvals() {
  const { user } = useApp();
  const [items, setItems] = useState([]);
  const [filter, setFilter] = useState("pending");
  const [active, setActive] = useState(null);
  const [mfaCode, setMfaCode] = useState("");
  const [rejectOpen, setRejectOpen] = useState(null);
  const [reason, setReason] = useState("");

  const load = () => {
    const params = new URLSearchParams();
    if (filter !== "all") params.set("status", filter);
    api.get(`/approvals?${params}`).then(({ data }) => setItems(data.items || []));
  };
  useEffect(() => { load(); }, [filter]);

  const approve = async (a) => {
    try {
      const { data } = await api.post(`/approvals/${a.approval_id}/approve`,
        { mfa_code: mfaCode || undefined });
      if (data.status === "executed") {
        toast.success("Approved & executed");
      } else {
        toast.success(`Signed · ${data.approvals_count}/${a.required_approvals}`);
      }
      setActive(null); setMfaCode("");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Approval failed");
    }
  };

  const doReject = async () => {
    try {
      await api.post(`/approvals/${rejectOpen.approval_id}/reject`, { reason });
      toast.success("Rejected");
      setRejectOpen(null); setReason("");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Reject failed");
    }
  };

  return (
    <div data-testid="approvals-page">
      <PageHeader title="Operations Queue" subtitle="Two-signer approvals — mint, fund creation, large redemptions" />

      <div className="mb-4 flex gap-2">
        {STATUS_FILTERS.map((f) => (
          <button key={f.value} onClick={() => setFilter(f.value)}
                  className={`px-4 py-1.5 rounded-full text-xs font-medium uppercase tracking-wider transition-colors ${
                    filter === f.value
                      ? "bg-[var(--primary)] text-white"
                      : "bg-[var(--surface)] border border-[var(--border)] text-[var(--fg-muted)] hover:text-[var(--fg)]"
                  }`}
                  data-testid={`filter-${f.value}`}>{f.label}</button>
        ))}
      </div>

      {items.length === 0 ? (
        <EmptyState title="No approvals in this view"
          message="Mint requests, fund creations and other critical ops will appear here for a second signer." />
      ) : (
        <div className="space-y-3">
          {items.map((a) => {
            const signed = a.approvals?.length || 0;
            const required = a.required_approvals || 1;
            const isOwn = user?.email === a.requested_by_email;
            const alreadySigned = a.approvals?.some(x => x.email === user?.email);
            const canAct = a.status === "pending" && !isOwn && !alreadySigned;
            return (
              <div key={a.approval_id} className="prosper-card p-5" data-testid={`approval-${a.approval_id}`}>
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-3 mb-2">
                      <span className="font-mono text-[10px] uppercase tracking-[0.15em] px-2 py-1 rounded-full"
                            style={{
                              background: "var(--primary-soft)",
                              color: "var(--primary)",
                            }}>
                        {a.action}
                      </span>
                      <StatusBadge value={a.status} />
                      <span className="text-xs text-[var(--fg-muted)]">{relativeTime(a.created_at)}</span>
                    </div>
                    <div className="font-display font-bold text-lg text-[var(--fg)] mb-1">
                      {a.action === "mint" && `Mint ${fmtMoney(a.payload?.amount || 0, "USD", 0)} PROS`}
                      {a.action === "fund.create" && `Create fund "${a.payload?.name}"`}
                      {a.action === "position.redeem.large" && `Large redemption`}
                    </div>
                    <div className="text-sm text-[var(--fg-muted)] mb-3">{a.reason || a.payload?.reason}</div>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-x-6 gap-y-2 text-xs">
                      <FieldRow label="Requester" value={a.requested_by_email} />
                      <FieldRow label="prosperTxId" value={<span className="font-mono">{(a.payload?.prosper_tx_id || "—").slice(0, 16)}…</span>} />
                      <FieldRow label="Signatures" value={
                        <span className="font-mono">
                          <span style={{ color: signed >= required ? "var(--success)" : "var(--warning)" }}>{signed}</span>
                          <span className="text-[var(--fg-muted)]">/{required}</span>
                        </span>
                      } />
                      <FieldRow label="Created" value={fmtDateTime(a.created_at)} />
                    </div>
                    {a.approvals?.length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {a.approvals.map((ap, i) => (
                          <span key={i} className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full"
                                style={{ background: "var(--primary-soft)", color: "var(--primary)" }}>
                            <CheckCircle size={11} weight="fill" /> {ap.email}
                          </span>
                        ))}
                      </div>
                    )}
                    {a.status === "rejected" && a.rejected_reason && (
                      <div className="mt-3 text-xs" style={{ color: "var(--danger)" }}>
                        Rejected by {a.rejected_by_email}: {a.rejected_reason}
                      </div>
                    )}
                  </div>
                  {canAct && (
                    <div className="flex flex-col gap-2 ml-4">
                      <Button onClick={() => setActive(a)} data-testid={`approve-btn-${a.approval_id}`}
                              className="rounded-full bg-[var(--success)] hover:opacity-90 text-white gap-1.5 h-9">
                        <ShieldCheck size={14} weight="bold" /> Approve
                      </Button>
                      <Button onClick={() => setRejectOpen(a)} data-testid={`reject-btn-${a.approval_id}`}
                              variant="outline"
                              className="rounded-full border-[var(--danger)]/40 text-[var(--danger)] hover:bg-[var(--danger)]/10 gap-1.5 h-9">
                        <XCircle size={14} weight="bold" /> Reject
                      </Button>
                    </div>
                  )}
                  {isOwn && a.status === "pending" && (
                    <div className="text-xs text-[var(--fg-muted)] ml-4 flex items-center gap-1.5">
                      <Clock size={14} /> Awaiting co-signer
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Approve modal with optional MFA */}
      <Dialog open={!!active} onOpenChange={(o) => !o && setActive(null)}>
        <DialogContent className="bg-[var(--surface)] border-[var(--border)] rounded-xl max-w-md" data-testid="approve-dialog">
          <DialogHeader>
            <DialogTitle className="font-display flex items-center gap-2">
              <ShieldCheck size={20} weight="fill" style={{ color: "var(--success)" }} />
              Confirm Approval
            </DialogTitle>
          </DialogHeader>
          {active && (
            <div className="space-y-3 py-2 text-sm">
              <div>
                <div className="text-[10px] uppercase tracking-wider text-[var(--fg-muted)]">Action</div>
                <div className="font-mono">{active.action}</div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wider text-[var(--fg-muted)]">Requester</div>
                <div>{active.requested_by_email}</div>
              </div>
              {active.action === "mint" && (
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-[var(--fg-muted)]">Amount</div>
                  <div className="font-mono text-lg">{fmtMoney(active.payload?.amount || 0, "USD", 0)} PROS</div>
                </div>
              )}
              <div className="space-y-1.5 pt-2">
                <Label className="text-xs uppercase tracking-wider text-[var(--fg-muted)]">MFA Code (if enabled)</Label>
                <Input placeholder="6-digit TOTP code" value={mfaCode}
                       onChange={(e) => setMfaCode(e.target.value)}
                       className="bg-[var(--bg)] border-[var(--border)] font-mono rounded-md"
                       data-testid="approval-mfa-code" />
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => { setActive(null); setMfaCode(""); }}
                    className="rounded-full" data-testid="approve-cancel">Cancel</Button>
            <Button onClick={() => approve(active)}
                    className="rounded-full bg-[var(--success)] hover:opacity-90 text-white"
                    data-testid="approve-confirm">Approve & Execute</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Reject modal */}
      <Dialog open={!!rejectOpen} onOpenChange={(o) => !o && setRejectOpen(null)}>
        <DialogContent className="bg-[var(--surface)] border-[var(--border)] rounded-xl max-w-md">
          <DialogHeader><DialogTitle className="font-display">Reject Approval</DialogTitle></DialogHeader>
          <div className="py-2">
            <Label className="text-xs uppercase tracking-wider text-[var(--fg-muted)]">Reason</Label>
            <Textarea value={reason} onChange={(e) => setReason(e.target.value)}
                      placeholder="Explain why this request is being rejected…"
                      className="bg-[var(--bg)] border-[var(--border)] rounded-md mt-1.5"
                      data-testid="reject-reason" />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRejectOpen(null)} className="rounded-full">Cancel</Button>
            <Button onClick={doReject}
                    className="rounded-full text-white"
                    style={{ background: "var(--danger)" }}
                    data-testid="reject-confirm">Reject Request</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

const FieldRow = ({ label, value }) => (
  <div>
    <div className="text-[10px] uppercase tracking-wider text-[var(--fg-muted)]">{label}</div>
    <div className="text-[var(--fg)]">{value}</div>
  </div>
);
