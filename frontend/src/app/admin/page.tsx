import { PageHeader } from "@/components/Page";
import { KpiCard } from "@prosper/ui";

export default function AdminHomePage() {
  return (
    <div>
      <PageHeader
        kicker="Phase 0 · Bootstrap"
        title="Admin Home"
        subtitle="Foundation in place. Business modules ship in the next phases."
      />
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <KpiCard label="Active Tenants" value="—" hint="Wires up in Phase 2" />
        <KpiCard label="AUM (USD)"      value="—" hint="Wires up in Phase 6" />
        <KpiCard label="Open Ops"       value="—" hint="Wires up in Phase 4" />
        <KpiCard label="KYC Pending"    value="—" hint="Wires up in Phase 3" />
      </div>

      <div className="prosper-card p-6">
        <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-2">
          Status
        </div>
        <h2 className="font-display font-bold text-xl text-fg mb-3">
          Bootstrap complete
        </h2>
        <ul className="text-sm text-fg-muted space-y-1.5">
          <li>✓ Monorepo (pnpm workspaces) wired with apps/api + apps/admin + packages/ui + packages/types.</li>
          <li>✓ Passwordless OTP auth (email → 4-digit code → JWT cookie, 7-day expiry).</li>
          <li>✓ Design system with Prosper palette + IBM Plex Sans / Chivo / Plex Mono.</li>
          <li>✓ Layout shell with collapsible sidebar, env switcher, alerts bell and avatar menu.</li>
          <li>✓ Docker Compose for api + mongo + redis + mailhog; Vitest + Pytest smoke tests.</li>
        </ul>
      </div>
    </div>
  );
}
