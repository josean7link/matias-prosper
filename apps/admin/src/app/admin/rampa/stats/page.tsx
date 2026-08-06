"use client";
import { KpiCard, PageHeader } from "@prosper/ui";
import { useTranslations } from "next-intl";
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
  BarChart, Bar, CartesianGrid, Legend,
} from "recharts";
import { ChartBar } from "lucide-react";
import {
  useProjectStats, useStatsTimeseries, fmtArsaAdmin,
} from "@/lib/admin-ramp";

/** Phase 16 · D — /admin/rampa/stats */
export default function RampStatsPage() {
  const tH = useTranslations("admin.headers");
  const tA = useTranslations("admin");
  return (
    <div className="space-y-6">
      <PageHeader
        crumbs={[{ label: tA("breadcrumb_admin") }, { label: tH("rampa_label") }, { label: tH("rampa_stats_bc") }]}
        title={tH("rampa_stats_title")}
        subtitle={tH("rampa_stats_subtitle")}
      />
      <RampStatsSection/>
    </div>
  );
}

/** Inline-embeddable version of the stats block. Used both by /admin/rampa/stats
 *  AND by the executive admin dashboard. */
export function RampStatsSection({ compact = false }: { compact?: boolean }) {
  const tc = useTranslations("admin.stats_charts");
  const stats = useProjectStats();
  const ts    = useStatsTimeseries();
  const points = ts.data?.points || [];

  return (
    <section className="space-y-4" data-testid="ramp-stats-section">
      <div className="flex items-center gap-2">
        <ChartBar size={14} className="text-primary"/>
        <h3 className="font-display font-bold text-lg text-fg">
          Rampa · AndesLabs
        </h3>
        <span className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
          ARSa first-class
        </span>
        {stats.data?.mode && (
          <span className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle ml-auto">
            mode: {stats.data.mode}
          </span>
        )}
      </div>

      <div className={`grid gap-3 ${compact
          ? "grid-cols-2 lg:grid-cols-4"
          : "grid-cols-2 lg:grid-cols-4"}`}
           data-testid="ramp-stats-kpis">
        <KpiCard
          testId="stats-tvl-arsa"
          label={tc("tvl_arsa")}
          value={fmtArsaAdmin(stats.data?.tvl_arsa || "0")}
          hint={tc("tvl_arsa_hint")}
          loading={stats.isLoading}/>
        <KpiCard
          testId="stats-accounts"
          label={tc("accounts")}
          value={String(stats.data?.accounts ?? "—")}
          hint={tc("wallets_count", { n: stats.data?.wallets ?? 0 })}
          loading={stats.isLoading}/>
        <KpiCard
          testId="stats-deposits-30d"
          label={tc("deposits_30d")}
          value={String(stats.data?.deposit_count_30d ?? "—")}
          hint={tc("deposits_vol_hint", { vol: fmtArsaAdmin(stats.data?.volume_arsa_30d || "0") })}
          loading={stats.isLoading}/>
        <KpiCard
          testId="stats-withdrawals-30d"
          label={tc("withdrawals_30d")}
          value={String(stats.data?.withdrawal_count_30d ?? "—")}
          hint={tc("cvus_hint", { n: stats.data?.cvu_count ?? 0 })}
          loading={stats.isLoading}/>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <div className="prosper-card p-4" data-testid="ramp-stats-chart-volume">
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
            {tc("volume_arsa_30d")}
          </div>
          <div className="font-display font-bold text-lg text-fg mb-2">
            {tc("daily_trend")}
          </div>
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={points}>
              <defs>
                <linearGradient id="volArsa" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%"   stopColor="#0b3aa3" stopOpacity={0.5}/>
                  <stop offset="100%" stopColor="#0b3aa3" stopOpacity={0.02}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#e6e6e8" vertical={false}/>
              <XAxis dataKey="ts" tick={{ fontSize: 10, fontFamily: "monospace" }}/>
              <YAxis tick={{ fontSize: 10, fontFamily: "monospace" }}
                     tickFormatter={(n: number) =>
                       n >= 1_000_000 ? `${(n/1_000_000).toFixed(1)}M`
                       : n >= 1_000 ? `${(n/1_000).toFixed(0)}k` : String(n)}/>
              <Tooltip formatter={(v: any) => fmtArsaAdmin(v)}
                        labelStyle={{ fontFamily: "monospace", fontSize: 11 }}/>
              <Area type="monotone" dataKey="volume_arsa"
                    stroke="#0b3aa3" strokeWidth={2}
                    fill="url(#volArsa)" name="ARSa"/>
            </AreaChart>
          </ResponsiveContainer>
        </div>

        <div className="prosper-card p-4" data-testid="ramp-stats-chart-flows">
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
            {tc("deposits_vs_withdrawals_30d")}
          </div>
          <div className="font-display font-bold text-lg text-fg mb-2">
            {tc("daily_count")}
          </div>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={points}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e6e6e8" vertical={false}/>
              <XAxis dataKey="ts" tick={{ fontSize: 10, fontFamily: "monospace" }}/>
              <YAxis tick={{ fontSize: 10, fontFamily: "monospace" }}/>
              <Tooltip labelStyle={{ fontFamily: "monospace", fontSize: 11 }}/>
              <Legend iconSize={8} wrapperStyle={{ fontSize: 11,
                                                     fontFamily: "monospace" }}/>
              <Bar dataKey="deposits"    fill="#16a34a" name={tc("deposits_label")}/>
              <Bar dataKey="withdrawals" fill="#0b3aa3" name={tc("withdrawals_label")}/>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {(stats.data?.mode === "mock" || ts.data?.mode === "mock") && (
        <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
          {tc("demo_mode")}
        </div>
      )}
    </section>
  );
}
