"use client";
import { useState } from "react";
import useSWR from "swr";
import { useTranslations } from "next-intl";
import { PageHeader } from "@prosper/ui";
import { RefreshCw } from "lucide-react";

import { KpiTile } from "@/components/KpiTile";
import { NavChart } from "@/components/dashboard/NavChart";
import { VolumeChart } from "@/components/dashboard/VolumeChart";
import { RevenueChart } from "@/components/dashboard/RevenueChart";
import { TopClientsTable } from "@/components/dashboard/TopClientsTable";
import { OpsQueuePanel } from "@/components/dashboard/OpsQueuePanel";
import { RecentActivity } from "@/components/dashboard/RecentActivity";
import ExportPdfButton from "@/components/dashboard/ExportPdfButton";
import IntegrationsHealthStrip from "@/components/dashboard/IntegrationsHealthStrip";
import { RampStatsSection } from "@/app/admin/rampa/stats/page";

import {
  useDashboardKpis, useNavHistory, useVolume,
  useRevenue, useTopClients, useOpsQueue, useRecentActivity,
} from "@/lib/dashboard";
import { useOpsQueueWS } from "@/lib/useOpsQueueWS";
import { api } from "@/lib/api";
import { fmtMoney, fmtNum, cn } from "@/lib/utils";

type Range = "7d" | "30d" | "90d";
const rangeDays: Record<Range, number> = { "7d": 7, "30d": 30, "90d": 90 };

export default function AdminHomePage() {
  const t = useTranslations("admin.home");
  const tBase = useTranslations("admin");
  const tt = useTranslations("admin.tooltips");
  const tooltips = {
    aum:     tt("aum"),
    nav:     tt("nav"),
    revenue: tt("revenue"),
    volume:  tt("volume"),
    active:  tt("active"),
    ops:     tt("ops"),
  };
  const [range, setRange] = useState<Range>("30d");

  const kpis     = useDashboardKpis(rangeDays[range]);
  const nav      = useNavHistory(90);
  const volume   = useVolume(rangeDays[range]);
  const revenue  = useRevenue(12);
  const clients  = useTopClients(8);
  const opsHttp  = useOpsQueue();
  const opsWs    = useOpsQueueWS();
  const activity = useRecentActivity(8);
  const meSwr    = useSWR<{ user: { email: string } }>("/v1/me", (p: string) => api(p));

  // Prefer WS data when available; fall back to HTTP polling
  const opsData = opsWs.data ?? opsHttp.data;

  const k = kpis.data;
  const navLast = nav.data?.items.at(-1);

  const refresh = () => {
    kpis.mutate();    nav.mutate();    volume.mutate();
    revenue.mutate(); clients.mutate(); opsHttp.mutate();
    activity.mutate();
  };
  const anyLoading = kpis.isLoading;

  return (
    <div data-testid="admin-home">
      <PageHeader
        breadcrumbs={[{ label: tBase("breadcrumb_admin"), href: "/admin" }, { label: t("breadcrumb") }]}
        kicker={t("kicker")}
        title={t("title")}
        subtitle={t("subtitle")}
        actions={
          <div className="flex items-center gap-2">
            <RangeSwitcher value={range} onChange={setRange} />
            <ExportPdfButton
              generatedAt={k?.generated_at ?? new Date().toISOString()}
              generatedBy={meSwr.data?.user?.email ?? "admin@prosper.foundation"}
              kpis={k}
              navLast={navLast}
              revenue={revenue.data?.items ?? []}
              topClients={clients.data?.items ?? []}
            />
            <button
              onClick={refresh}
              className="prosper-btn-ghost h-9 text-xs gap-1.5"
              data-testid="dashboard-refresh"
              disabled={anyLoading}
            >
              <RefreshCw size={13} className={anyLoading ? "animate-spin" : undefined} />
              {t("refresh")}
            </button>
          </div>
        }
      />

      <IntegrationsHealthStrip />

      {/* Phase 16 — Ramp (Andes) section inline on the executive dashboard */}
      <div className="mb-6">
        <RampStatsSection compact />
      </div>

      {/* KPI row */}
      <section
        className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mb-6"
        data-testid="kpi-row"
      >
        <KpiTile
          label={t("kpi_aum")}
          value={fmtMoney(k?.aum_usd)}
          delta={k?.aum_delta_24h}
          hint={t("kpi_24h")}
          loading={kpis.isLoading}
          tooltip={tooltips.aum}
        />
        <KpiTile
          label={t("kpi_nav")}
          value={navLast?.nav != null ? navLast.nav.toFixed(6) : (k?.nav?.toFixed(6) ?? "—")}
          delta={k?.nav_delta_24h}
          hint={t("kpi_24h")}
          loading={kpis.isLoading || nav.isLoading}
          tooltip={tooltips.nav}
        />
        <KpiTile
          label={t("kpi_revenue_mtd")}
          value={fmtMoney(k?.revenue_mtd)}
          hint={t("kpi_revenue_ytd_hint", { value: fmtMoney(k?.revenue_ytd) })}
          loading={kpis.isLoading}
          tooltip={tooltips.revenue}
        />
        <KpiTile
          label={t("kpi_volume", { range })}
          value={fmtMoney(k?.volume_30d)}
          hint={t("kpi_volume_hint")}
          loading={kpis.isLoading}
          tooltip={tooltips.volume}
        />
        <KpiTile
          label={t("kpi_active")}
          value={fmtNum(k?.active_clients)}
          hint={t("kpi_active_hint")}
          loading={kpis.isLoading}
          href="/admin/clients"
          tooltip={tooltips.active}
        />
        <KpiTile
          label={t("kpi_ops")}
          value={fmtNum(k?.operations_queue)}
          hint={t("kpi_ops_hint")}
          loading={kpis.isLoading}
          href="/admin/operations"
          tooltip={tooltips.ops}
        />
      </section>

      {/* Main grid: charts (left, 8 cols) + right side (ops queue + recent activity) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* LEFT — charts + table */}
        <div className="lg:col-span-8 space-y-6">
          <ChartCard
            title={t("chart_nav_title")}
            subtitle={t("chart_nav_subtitle")}
            kpi={navLast?.nav != null ? navLast.nav.toFixed(6) : "—"}
            loading={nav.isLoading}
          >
            <NavChart data={nav.data?.items ?? []} />
          </ChartCard>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <ChartCard
              title={t("chart_volume_title")}
              subtitle={t("chart_volume_subtitle", { range })}
              kpi={fmtMoney(k?.volume_30d)}
              loading={volume.isLoading}
            >
              <VolumeChart data={volume.data?.items ?? []} />
            </ChartCard>

            <ChartCard
              title={t("chart_revenue_title")}
              subtitle={t("chart_revenue_subtitle")}
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
                  {t("top_clients_kicker")}
                </div>
                <h2 className="font-display font-bold text-lg text-fg">{t("top_clients_title")}</h2>
              </div>
              <a
                href="/admin/clients"
                className="text-xs font-mono uppercase tracking-wider text-primary hover:underline"
              >
                {t("view_all")} →
              </a>
            </div>
            <TopClientsTable data={clients.data?.items ?? []} loading={clients.isLoading} />
          </section>
        </div>

        {/* RIGHT — ops queue + recent activity (sticky stack on desktop) */}
        <div className="lg:col-span-4">
          <div className="lg:sticky lg:top-4 space-y-6">
            <OpsQueuePanel
              data={opsData}
              loading={opsHttp.isLoading && !opsWs.data}
              wsStatus={opsWs.status}
            />
            <RecentActivity
              data={activity.data?.items ?? []}
              loading={activity.isLoading}
            />
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
