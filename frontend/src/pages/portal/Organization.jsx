import { useEffect, useState } from "react";
import api from "@/lib/api";
import { useApp } from "@/contexts/AppContext";
import { PageHeader, EnvPill, StatusBadge } from "@/components/common";
import { fmtMoney, fmtDate } from "@/lib/format";

export default function PortalOrganization() {
  const { user } = useApp();
  const [orgs, setOrgs] = useState([]);
  useEffect(() => { api.get("/organizations").then(({ data }) => setOrgs(data.items || [])); }, []);
  // Pick first org (real app: filter by user's org_id)
  const org = orgs[0];

  return (
    <div data-testid="portal-organization">
      <PageHeader title="My Organization" subtitle="Corporate & regulatory information" />
      {!org ? <div className="text-[var(--fg-muted)]">No organization attached to your account yet.</div> : (
        <div className="prosper-card p-6">
          <div className="flex justify-between items-start mb-6">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-[var(--fg-muted)] font-mono">Organization</div>
              <h2 className="font-display font-bold text-2xl">{org.name}</h2>
              <div className="text-sm text-[var(--fg-muted)] mt-1">{org.legal_name}</div>
            </div>
            <div className="flex flex-col gap-1 items-end">
              <EnvPill env={org.environment} />
              <StatusBadge value={org.status} />
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-0 tight-grid border border-[var(--border)]">
            <Cell label="Country" value={org.country || "—"} />
            <Cell label="Type" value={org.type} />
            <Cell label="Contact Email" value={org.contact_email || "—"} />
            <Cell label="AUM" value={fmtMoney(org.aum_usd)} />
            <Cell label="Active investors" value={org.active_investors} />
            <Cell label="Created" value={fmtDate(org.created_at)} />
          </div>
        </div>
      )}
    </div>
  );
}

const Cell = ({ label, value }) => (
  <div className="p-4 bg-[var(--surface)]">
    <div className="text-[10px] uppercase tracking-wider text-[var(--fg-muted)] mb-1">{label}</div>
    <div className="text-[var(--fg)] capitalize">{value}</div>
  </div>
);
