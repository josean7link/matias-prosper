"use client";
import { Badge } from "@prosper/ui";
import { Mail } from "lucide-react";
import { useClientEmails } from "@/lib/admin-clients";
import { fmtDate } from "@/lib/utils";

export default function KybTab({ orgId }: { orgId: string }) {
  // KYB docs come from the legacy /compliance/kyb seed. For now we surface the
  // /admin/compliance/kyb page link + the outbound emails (invitation, kyb link)
  // sent to this org. When the cliente sube docs vía /apply (Phase 7+) acá los
  // mostramos como grid con preview.
  const emails = useClientEmails(orgId);
  return (
    <div className="space-y-4" data-testid="tab-content-kyb">
      <div className="prosper-card p-5">
        <h3 className="font-display font-bold text-sm mb-2">KYB documents</h3>
        <p className="text-xs text-fg-muted mb-3">
          La gestión completa de KYB con checklist + decisión está en
          <a href={`/admin/compliance/kyb`} className="text-primary hover:underline ml-1">
            /admin/compliance/kyb</a>.
          Acá se mostrarán los documentos que suba el cliente vía /apply una vez que
          complete el link de onboarding.
        </p>
      </div>
      <div className="prosper-card p-5">
        <h3 className="font-display font-bold text-sm mb-2 flex items-center gap-2">
          <Mail size={13}/> Emails enviados a este cliente
        </h3>
        <table className="w-full text-xs">
          <thead className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
            <tr className="border-b border-border">
              <th className="text-left py-2">When</th>
              <th className="text-left py-2">Template</th>
              <th className="text-left py-2">To</th>
              <th className="text-left py-2">Status</th>
              <th className="text-left py-2">Preview</th>
            </tr>
          </thead>
          <tbody>
            {(emails.data?.items ?? []).map((e: any) => (
              <tr key={e.email_id} className="border-b border-border"
                  data-testid={`email-row-${e.email_id}`}>
                <td className="py-2 font-mono text-[10px]">{fmtDate(e.created_at)}</td>
                <td className="py-2 font-mono">{e.template}</td>
                <td className="py-2 font-mono text-[11px]">{e.to}</td>
                <td className="py-2">
                  <Badge size="sm"
                    tone={e.status === "sent" ? "success"
                            : e.status === "failed" ? "danger" : "warning"}>
                    {e.status}</Badge>
                </td>
                <td className="py-2">
                  <a href={`/api/v1/admin/clients/${orgId}/emails/${e.email_id}/preview`}
                     target="_blank" rel="noreferrer"
                     data-testid={`email-preview-${e.email_id}`}
                     className="text-primary hover:underline text-[11px]">
                    open HTML →
                  </a>
                </td>
              </tr>
            ))}
            {(emails.data?.items ?? []).length === 0 && (
              <tr><td colSpan={5} className="py-6 text-center text-fg-subtle italic">
                Sin emails enviados todavía.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
