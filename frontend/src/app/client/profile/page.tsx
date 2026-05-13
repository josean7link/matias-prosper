"use client";
import { PageHeader, Badge } from "@prosper/ui";
import { RefreshButton } from "@/components/PageActions";
import { Building2, Mail, Globe, Hash, ShieldCheck, User as UserIcon } from "lucide-react";
import { useClientMe } from "@/lib/client-portal";

const KYB_TONE: Record<string, "success" | "warning" | "info" | "danger"> = {
  approved:   "success",
  pending:    "warning",
  needs_info: "warning",
  in_review:  "info",
  rejected:   "danger",
};

export default function ClientProfilePage() {
  const { data, isLoading } = useClientMe();
  const org = data?.org;
  const user = data?.user;

  return (
    <div data-testid="client-profile">
      <PageHeader
        breadcrumbs={[
          { label: "Client", href: "/client" },
          { label: "Perfil" },
        ]}
        kicker="Client · Phase 7"
        title="Perfil"
        subtitle="Datos de tu organización y usuario. Para cambios contactá a soporte."
        actions={<RefreshButton />}
      />

      {isLoading || !org || !user ? (
        <div className="prosper-card p-8 animate-pulse h-40" />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
          {/* Org card */}
          <section className="prosper-card p-6 lg:col-span-2 space-y-4" data-testid="org-card">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
                  Organización
                </div>
                <h2 className="font-display font-bold text-xl text-fg mt-1 flex items-center gap-2">
                  <Building2 size={16} />
                  {org.commercial_name || org.legal_name || org.org_id}
                </h2>
                {org.legal_name && org.commercial_name && (
                  <p className="text-xs text-fg-muted mt-1">Razón social · {org.legal_name}</p>
                )}
              </div>
              <Badge tone={KYB_TONE[org.kyb_status] || "default"}>
                KYB · {org.kyb_status}
              </Badge>
            </div>

            <div className="h-px bg-border" />

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3 text-sm">
              <DataRow icon={<Hash size={12} />} label="Org ID" value={org.org_id} mono />
              <DataRow icon={<Globe size={12} />} label="País" value={org.country || "—"} />
              <DataRow icon={<ShieldCheck size={12} />} label="Tier" value={org.tier} />
              <DataRow icon={<Globe size={12} />} label="Entorno" value={org.env} mono />
            </div>

            {org.kyb_status === "rejected" && org.kyb_reject_reason && (
              <div className="border border-danger/30 bg-danger/5 rounded p-3"
                   data-testid="kyb-reject-reason">
                <div className="text-[10px] font-mono uppercase tracking-wider text-danger mb-1">
                  Motivo de rechazo
                </div>
                <p className="text-xs text-fg">{org.kyb_reject_reason}</p>
              </div>
            )}
          </section>

          {/* User card */}
          <section className="prosper-card p-6 space-y-4" data-testid="user-card">
            <div>
              <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
                Tu cuenta
              </div>
              <h2 className="font-display font-bold text-xl text-fg mt-1 flex items-center gap-2">
                <UserIcon size={16} />
                {user.full_name || user.email}
              </h2>
            </div>

            <div className="h-px bg-border" />

            <div className="space-y-3 text-sm">
              <DataRow icon={<Mail size={12} />} label="Email" value={user.email} />
              <DataRow icon={<ShieldCheck size={12} />} label="Rol" value={user.role} mono />
              <DataRow icon={<Hash size={12} />} label="User ID" value={user.user_id} mono small />
            </div>

            <div className="border-t border-border pt-3 text-[11px] text-fg-subtle">
              ¿Necesitás invitar a otro miembro de tu equipo o cambiar datos?
              Escribinos a <a className="text-primary hover:underline"
                              href="mailto:support@prosper.foundation">support@prosper.foundation</a>.
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

function DataRow({ icon, label, value, mono, small }:
  { icon?: React.ReactNode; label: string; value: string; mono?: boolean; small?: boolean }) {
  return (
    <div>
      <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle flex items-center gap-1 mb-1">
        {icon} {label}
      </div>
      <div className={`${mono ? "font-mono" : ""} ${small ? "text-xs" : "text-sm"} text-fg break-all`}>
        {value}
      </div>
    </div>
  );
}
