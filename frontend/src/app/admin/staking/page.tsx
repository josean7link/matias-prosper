"use client";
/**
 * Gestión de Staking — módulo admin (/admin/staking).
 * Tabs compartidos con el portal cliente en components/staking/StakingTabs.
 * Widgets de tesorería + sync son exclusivos del admin.
 * i18n: namespace `staking` (next-intl, EN/ES).
 */
import { useState } from "react";
import useSWR from "swr";
import { Coins, Copy, Loader2, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { PageHeader } from "@prosper/ui";
import { api } from "@/lib/api";
import {
  StakingTabs, copyText, fmtAmount, fmtDate, short, useLoc,
} from "@/components/staking/StakingTabs";

const fetcher = (p: string) => api<any>(p);

interface Treasury {
  address: string | null;
  balanceUSDC: string | number | null;
  balanceARSA: string | number | null;
  mode: string;
  refreshed_at: string;
}
interface SyncStatus {
  enabled: boolean; mode: string; interval_minutes: number;
  last_run: { ok: boolean; processed: number; created: number; updated: number;
               finished_at: string } | null;
}

function TreasuryAndSync() {
  const t = useTranslations("staking");
  const loc = useLoc();
  const { data: tr, error: tErr, mutate: mutT, isLoading: tLoading } =
    useSWR<Treasury>("/v1/admin/prosper/treasury", fetcher);
  const { data: s, mutate: mutS } =
    useSWR<SyncStatus>("/v1/admin/prosper/staking-sync/status", fetcher,
                        { refreshInterval: 60_000 });
  const [running, setRunning] = useState(false);

  const runNow = async () => {
    setRunning(true);
    try {
      await api("/v1/admin/prosper/staking-sync/run", { method: "POST" });
      toast.success(t("sync.run_ok"));
      mutS(); mutT();
    } catch (e: any) {
      toast.error(e?.message || t("sync.run_failed"));
    } finally { setRunning(false); }
  };

  const cell = "rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--surface))] p-4";
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-6" data-testid="staking-cms-widgets">
      <div className={cell} data-testid="staking-treasury-usdc">
        <p className="text-[10px] uppercase tracking-wider text-[rgb(var(--fg-muted))]">{t("treasury.usdc")}</p>
        <p className="text-2xl font-mono mt-1">
          {tErr ? "—" : tLoading ? "…" : fmtAmount(tr?.balanceUSDC, "usdc", loc)}
        </p>
      </div>
      <div className={cell} data-testid="staking-treasury-arsa">
        <p className="text-[10px] uppercase tracking-wider text-[rgb(var(--fg-muted))]">{t("treasury.arsa")}</p>
        <p className="text-2xl font-mono mt-1">
          {tErr ? "—" : tLoading ? "…" : fmtAmount(tr?.balanceARSA, "arsa", loc)}
        </p>
        {tr?.address && (
          <button className="mt-1 text-[11px] font-mono text-[rgb(var(--fg-muted))] hover:underline"
                  onClick={() => copyText(tr.address!, t("copied", { label: t("treasury.address_label") }))}
                  data-testid="staking-treasury-address">
            {short(tr.address)} <Copy className="inline" size={10} />
          </button>
        )}
      </div>
      <div className={cell} data-testid="staking-sync-widget">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-[10px] uppercase tracking-wider text-[rgb(var(--fg-muted))]">{t("sync.title")}</p>
            <p className="text-sm mt-1">
              {s ? (s.enabled ? t("sync.every", { n: s.interval_minutes }) : t("sync.disabled")) : "…"}
            </p>
            <p className="text-[11px] text-[rgb(var(--fg-muted))] mt-0.5" data-testid="staking-sync-lastrun">
              {s?.last_run
                ? t("sync.last_run", {
                    date: fmtDate(s.last_run.finished_at, loc),
                    processed: s.last_run.processed,
                    created: s.last_run.created ?? 0,
                    updated: s.last_run.updated ?? 0 })
                : t("sync.no_runs")}
            </p>
            {s?.last_run && s.last_run.ok === false && (
              <p className="text-[11px] text-red-500 mt-0.5" data-testid="staking-sync-failed">
                {t("sync.last_failed")}
              </p>
            )}
            {tr && (
              <p className="text-[10px] text-[rgb(var(--fg-muted))] mt-1" data-testid="staking-treasury-meta">
                {t("treasury.meta", { mode: tr.mode, date: fmtDate(tr.refreshed_at, loc) })}
              </p>
            )}
          </div>
          <button
            onClick={runNow} disabled={running}
            className="inline-flex items-center gap-1.5 rounded-md border border-[rgb(var(--border))] px-2.5 py-1.5 text-xs hover:bg-[rgb(var(--surface-hover))] disabled:opacity-50"
            data-testid="staking-sync-run-btn">
            {running ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
            {t("sync.run")}
          </button>
        </div>
        {tErr && (
          <p className="text-[11px] text-red-500 mt-1" data-testid="staking-cms-error">
            {t("treasury.cms_error", { msg: String((tErr as any)?.message || tErr) })}
          </p>
        )}
      </div>
    </div>
  );
}

export default function AdminStakingPage() {
  const t = useTranslations("staking.page");
  return (
    <div data-testid="admin-staking-page">
      <PageHeader
        breadcrumbs={[{ label: t("admin_breadcrumb_home"), href: "/admin" }, { label: t("breadcrumb") }]}
        kicker={t("admin_kicker")}
        title={t("title")}
        subtitle={t("admin_subtitle")}
        actions={<Coins size={20} className="text-[rgb(var(--fg-muted))]" />}
      />
      <TreasuryAndSync />
      <StakingTabs base="/v1/admin/prosper" />
    </div>
  );
}
