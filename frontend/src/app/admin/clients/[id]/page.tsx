"use client";
import { useState } from "react";
import { useParams } from "next/navigation";
import { PageHeader, Badge } from "@prosper/ui";
import { Pause, Play, ArrowLeft, Mail, Key, Link as LinkIcon } from "lucide-react";
import { toast } from "sonner";
import {
  useClient, pauseClient, reactivateClient, makeLink,
} from "@/lib/admin-clients";
import { cn, fmtMoney } from "@/lib/utils";
import InfoTab from "./_tabs/InfoTab";
import UsersTab from "./_tabs/UsersTab";
import KybTab from "./_tabs/KybTab";
import ApiKeysTab from "./_tabs/ApiKeysTab";
import WebhooksTab from "./_tabs/WebhooksTab";
import PositionsTab from "./_tabs/PositionsTab";
import TransactionsTab from "./_tabs/TransactionsTab";
import ComplianceTab from "./_tabs/ComplianceTab";
import AuditTab from "./_tabs/AuditTab";

type Tab = "info" | "users" | "kyb" | "api_keys" | "webhooks" | "positions" | "transactions" | "compliance" | "audit";
const TABS: { id: Tab; label: string }[] = [
  { id: "info",         label: "Información" },
  { id: "users",        label: "Usuarios" },
  { id: "kyb",          label: "KYB docs" },
  { id: "api_keys",     label: "API keys" },
  { id: "webhooks",     label: "Webhooks" },
  { id: "positions",    label: "Posiciones" },
  { id: "transactions", label: "Transacciones" },
  { id: "compliance",   label: "Compliance" },
  { id: "audit",        label: "Audit log" },
];

const KYB_TONE: Record<string, "success" | "info" | "warning" | "danger" | "auto"> = {
  approved: "success", pending: "warning", in_review: "info",
  rejected: "danger", needs_info: "warning",
};

export default function ClientDetailPage() {
  const params = useParams();
  const orgId = String(params?.id || "");
  const swr = useClient(orgId);
  const [tab, setTab] = useState<Tab>("info");

  const onPauseToggle = async () => {
    if (!swr.data) return;
    try {
      if (swr.data.org.paused) {
        await reactivateClient(orgId); toast.success("Cliente reactivado");
      } else {
        await pauseClient(orgId); toast.success("Cliente pausado");
      }
      await swr.mutate();
    } catch (e: any) { toast.error(e?.message || "Failed"); }
  };

  const copyLink = async (purpose: "kyb" | "reset_password" | "invite") => {
    try {
      const res = await makeLink(orgId, purpose, { send_email: false });
      await navigator.clipboard?.writeText(res.url);
      toast.success(`Link ${purpose} copiado al portapapeles · vence ${new Date(res.expires_at).toLocaleString()}`);
    } catch (e: any) { toast.error(e?.message || "Failed"); }
  };

  const o = swr.data?.org;

  return (
    <div data-testid="admin-client-detail-page">
      <a href="/admin/clients"
        className="inline-flex items-center gap-1.5 text-[11px] font-mono text-fg-subtle hover:text-fg mb-2">
        <ArrowLeft size={11}/> Clientes
      </a>

      <PageHeader
        breadcrumbs={[{ label: "Admin", href: "/admin" },
                      { label: "Clientes", href: "/admin/clients" },
                      { label: o?.legal_name || "..." }]}
        kicker={`Phase 6 · ${o?.org_id || ""}`}
        title={o?.legal_name || "Loading…"}
        subtitle={o ? `${o.commercial_name} · ${o.country} · ${o.type} · ${o.env}` : ""}
        actions={
          <div className="flex items-center gap-2">
            <button onClick={() => copyLink("kyb")}
              data-testid="detail-link-kyb"
              className="prosper-btn-ghost h-9 text-xs gap-1.5">
              <LinkIcon size={12}/> KYB link
            </button>
            <button onClick={() => copyLink("reset_password")}
              data-testid="detail-link-reset"
              className="prosper-btn-ghost h-9 text-xs gap-1.5">
              <Key size={12}/> Reset pass
            </button>
            <button onClick={() => copyLink("invite")}
              data-testid="detail-link-invite"
              className="prosper-btn-ghost h-9 text-xs gap-1.5">
              <Mail size={12}/> Invite link
            </button>
            {o && (
              <button onClick={onPauseToggle}
                data-testid="detail-pause-toggle"
                className={cn("h-9 px-3 rounded text-xs gap-1.5 inline-flex items-center font-medium",
                              o.paused ? "bg-success text-white" : "border border-danger/40 text-danger hover:bg-danger/10")}>
                {o.paused ? <><Play size={12}/> Reactivar</>
                          : <><Pause size={12}/> Pausar</>}
              </button>
            )}
          </div>
        }
      />

      {/* Status badges row */}
      {o && (
        <div className="flex flex-wrap items-center gap-2 mb-4 -mt-2">
          <Badge tone={KYB_TONE[o.kyb_status] || "auto"}>KYB · {o.kyb_status}</Badge>
          <Badge tone="auto">Tier · {o.tier}</Badge>
          {o.paused && <Badge tone="warning">PAUSADO</Badge>}
          {swr.data && (
            <>
              <span className="text-[11px] font-mono text-fg-subtle">·</span>
              <span className="text-[11px] font-mono text-fg-muted">
                {swr.data.metrics.users_count} users · {swr.data.metrics.active_positions} positions
                · vol total {fmtMoney(swr.data.metrics.volume_total_usd)}
              </span>
            </>
          )}
        </div>
      )}

      {/* Tabs */}
      <div className="flex flex-wrap border-b border-border mb-5 -mx-1" data-testid="client-tabs">
        {TABS.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)}
            data-testid={`tab-${t.id}`}
            className={cn("px-3 py-2 text-xs font-mono uppercase tracking-wider transition-colors border-b-2 -mb-px mx-0.5",
              tab === t.id ? "border-primary text-fg"
                            : "border-transparent text-fg-subtle hover:text-fg")}>
            {t.label}
          </button>
        ))}
      </div>

      <div>
        {tab === "info"         && <InfoTab orgId={orgId} org={o} onSaved={() => swr.mutate()}/>}
        {tab === "users"        && <UsersTab orgId={orgId}/>}
        {tab === "kyb"          && <KybTab orgId={orgId}/>}
        {tab === "api_keys"     && <ApiKeysTab orgId={orgId}/>}
        {tab === "webhooks"     && <WebhooksTab orgId={orgId}/>}
        {tab === "positions"    && <PositionsTab orgId={orgId}/>}
        {tab === "transactions" && <TransactionsTab orgId={orgId}/>}
        {tab === "compliance"   && <ComplianceTab orgId={orgId} risk={swr.data?.risk}/>}
        {tab === "audit"        && <AuditTab orgId={orgId}/>}
      </div>
    </div>
  );
}
