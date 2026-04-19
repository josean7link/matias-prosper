import { useEffect, useState } from "react";
import api from "@/lib/api";
import { PageHeader, StatusBadge, EmptyState } from "@/components/common";
import { fmtDate } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";

export default function Compliance() {
  const [items, setItems] = useState([]);

  const load = async () => {
    const { data } = await api.get("/compliance/queue");
    setItems(data.items || []);
  };
  useEffect(() => { load(); }, []);

  const decide = async (reviewId, decision) => {
    await api.post(`/compliance/${reviewId}/decide`, { decision });
    toast.success(`Decision: ${decision}`);
    load();
  };

  return (
    <div data-testid="compliance-page">
      <PageHeader title="Compliance Workspace" subtitle={`${items.length} reviews in queue`} />
      {items.length === 0 ? <EmptyState title="No reviews" /> : (
        <div className="prosper-card overflow-hidden">
          <table className="data-table w-full">
            <thead><tr>
              <th className="text-left px-4 py-3">Applicant</th>
              <th className="text-left px-4 py-3">KYC</th>
              <th className="text-left px-4 py-3">AML</th>
              <th className="text-left px-4 py-3">Sanctions</th>
              <th className="text-left px-4 py-3">PEP</th>
              <th className="text-left px-4 py-3">Travel Rule</th>
              <th className="text-left px-4 py-3">Decision</th>
              <th className="text-right px-4 py-3">Actions</th>
            </tr></thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.review_id} data-testid={`compliance-row-${r.review_id}`}>
                  <td className="px-4 py-3">
                    <div className="text-white">{r.case?.applicant_name || "—"}</div>
                    <div className="text-xs text-[#555] font-mono">{r.case?.applicant_email}</div>
                  </td>
                  <td className="px-4 py-3"><StatusBadge value={r.kyc_status} /></td>
                  <td className="px-4 py-3"><StatusBadge value={r.aml_check} /></td>
                  <td className="px-4 py-3"><StatusBadge value={r.sanctions_check} /></td>
                  <td className="px-4 py-3"><StatusBadge value={r.pep_check} /></td>
                  <td className="px-4 py-3"><StatusBadge value={r.travel_rule} /></td>
                  <td className="px-4 py-3"><StatusBadge value={r.decision} /></td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex gap-1 justify-end">
                      <Button size="sm" variant="outline" onClick={() => decide(r.review_id, "rejected")}
                              className="h-7 text-xs border-[#FF3D00]/30 text-[#FF3D00] rounded-sm"
                              data-testid={`reject-${r.review_id}`}>Reject</Button>
                      <Button size="sm" onClick={() => decide(r.review_id, "approved")}
                              className="h-7 text-xs bg-[#00C853] text-black hover:bg-[#00B84A] rounded-sm"
                              data-testid={`approve-${r.review_id}`}>Approve</Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
