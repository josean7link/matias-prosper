"use client";
import { useState } from "react";
import { PageHeader } from "@prosper/ui";
import { RefreshCw } from "lucide-react";

import { KpiTile } from "@/components/KpiTile";
import { NavChart } from "@/components/dashboard/NavChart";
import { VolumeChart } from "@/components/dashboard/VolumeChart";
import { RevenueChart } from "@/components/dashboard/RevenueChart";
import { TopClientsTable } from "@/components/dashboard/TopClientsTable";
import { OpsQueuePanel } from "@/components/dashboard/OpsQueuePanel";

import {
  useDashboardKpis, useNavHistory, useVolume,
  useRevenue, useTopClients, useOpsQueue,
} from "@/lib/dashboard";
import { fmtMoney, fmtNum, cn } from "@/lib/utils";

type Range = "7d" | "30d" | "90d";
const rangeDays: Record<Range, number> = { "7d": 7, "30d": 30, "90d": 90 };

export default function AdminHomePage() {
  const [range, setRange] = useState<Range>("30d");

  const kpis     = useDashboardKpis(rangeDays[range]);
  const nav      = useNavHistory(90);
  const volume   = useVolume(rangeDays[range]);
  const revenue  = useRevenue(12);
  const clients  = useTopClients(8);
  const ops      = useOpsQueue();

  const k = kpis.data;
  const navLast = nav.data?.items.at(-1)?.nav;

  const refresh = () => {
    kpis.mutate();    nav.mutate();    volume.mutate();
    revenue.mutate(); clients.mutate(); ops.mutate();
  };
  const anyLoading = kpis.isLoading || ops.isLoading;

  return (
    <div data-testid="admin-home">
      <PageHeader
        breadcrumbs={[{ label: "Admin", href: "/admin" }, { label: "Home" }]}
        kicker="Phase 2 · Operations"
        title="Admin Home"
        subtitle="Real-time view of AUM, revenue, on-chain volume and operations queue."
        actions={
          <div className="flex items-center gap-2">
            <RangeSwitcher value={range} onChange={setRange} />
            <button
              onClick={refresh}
              className="prosper-btn-ghost h-9 text-xs gap-1.5"
              data-testid="dashboard-refresh"
              disabled={anyLoading}
            >
              <RefreshCw size={13} className={anyLoading ? "animate-spin" : undefined} />
              Refresh
            </button>
          </div>
        }
      />

      {/* KPI row */}
      <section
        className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mb-6"
        data-testid="kpi-row"
      >
        <KpiTile
          label="AUM (USD)"
          value={fmtMoney(k?.aum_usd)}
          delta={k?.aum_delta_24h}
          hint="24h"
          loading={kpis.isLoading}
        />
        <KpiTile
          label="NAV"
          value={navLast != null ? navLast.toFixed(6) : (k?.nav?.toFixed(6) ?? "—")}
          delta={k?.nav_delta_24h}
          hint="24h"
          loading={kpis.isLoading || nav.isLoading}
        />
        <KpiTile
          label="Revenue · MTD"
          value={fmtMoney(k?.revenue_mtd)}
          hint={`YTD ${fmtMoney(k?.revenue_ytd)}`}
          loading={kpis.isLoading}
        />
        <KpiTile
          label={`Volume · ${range}`}
          value={fmtMoney(k?.volume_30d)}
          hint="subscribe + redeem"
          loading={kpis.isLoading}
        />
        <KpiTile
          label="Active Clients"
          value={fmtNum(k?.active_clients)}
          hint="with open positions"
          loading={kpis.isLoading}
          href="/admin/clients"
        />
        <KpiTile
          label="Ops Queue"
          value={fmtNum(k?.operations_queue)}
          hint="pending approvals"
          loading={kpis.isLoading}
          href="/admin/operations"
        />
      </section>

      {/* Main grid: charts (left, 8 cols) + ops queue (right, 4 cols) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* LEFT — charts + table */}
        <div className="lg:col-span-8 space-y-6">
          <ChartCard
            title="NAV"
            subtitle="Daily net asset value · 90 days"
            kpi={navLast != null ? navLast.toFixed(6) : "—"}
            loading={nav.isLoading}
          >
            <NavChart data={nav.data?.items ?? []} />
          </ChartCard>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <ChartCard
              title="Volume"
              subtitle={`Subscribe vs redeem · ${range}`}
              kpi={fmtMoney(k?.volume_30d)}
              loading={volume.isLoading}
            >
              <VolumeChart data={volume.data?.items ?? []} />
            </ChartCard>

            <ChartCard
              title="Revenue"
              subtitle="Fee revenue · last 12 months"
              kpi={fmtMoney(k?.revenue_ytd)}
              loading={revenue.isLoading}
            >
              <RevenueChart data={revenue.data?.items ?? []} />
            </ChartCard>
          </div>

          <section data-testid="top-clients">
            <div className="flex items-end justify-between mb-3">
              <div>
                <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
                  Top Clients
                </div>
                <h2 className="font-display font-bold text-lg text-fg">By AUM</h2>
              </div>
              <a
                href="/admin/clients"
                className="text-xs font-mono uppercase tracking-wider text-primary hover:underline"
              >
                View all →
              </a>
            </div>
            <TopClientsTable data={clients.data?.items ?? []} loading={clients.isLoading} />
          </section>
        </div>

        {/* RIGHT — operations queue (sticky on desktop) */}
        <div className="lg:col-span-4">
          <div className="lg:sticky lg:top-4">
            <OpsQueuePanel data={ops.data} loading={ops.isLoading} />
          </div>
        </div>
      </div>
    </div>
  );
}

/* ---------- helpers ---------- */

function RangeSwitcher({ value, onChange }: { value: Range; onChange: (v: Range) => void }) {
  return (
    <div
      className="inline-flex items-center bg-surface border border-border rounded p-0.5 text-[11px] font-mono uppercase tracking-wider"
      data-testid="range-switcher"
      role="tablist"
    >
      {(["7d", "30d", "90d"] as const).map((r) => (
        <button
          key={r}
          role="tab"
          aria-selected={r === value}
          onClick={() => onChange(r)}
          data-testid={`range-${r}`}
          className={cn(
            "px-2.5 h-7 rounded transition-colors",
            r === value
              ? "bg-fg text-bg"
              : "text-fg-subtle hover:text-fg",
          )}
        >
          {r}
        </button>
      ))}
    </div>
  );
}

interface ChartCardProps {
  title: string;
  subtitle?: string;
  kpi?: string;
  loading?: boolean;
  children: React.ReactNode;
}

function ChartCard({ title, subtitle, kpi, loading, children }: ChartCardProps) {
  return (
    <div className="prosper-card p-5" data-testid={`chart-card-${title.toLowerCase()}`}>
      <div className="flex items-start justify-between mb-4 gap-4">
        <div>
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
            {title}
          </div>
          {subtitle && (
            <div className="text-[11px] text-fg-subtle font-mono mt-0.5">{subtitle}</div>
          )}
        </div>
        {kpi && (
          <div className="font-display font-bold font-mono text-xl text-fg leading-none tabular">
            {kpi}
          </div>
        )}
      </div>
      {loading ? (
        <div className="h-[240px] rounded bg-surface-hover animate-pulse" />
      ) : (
        children
      )}
    </div>
  );
}
