"use client";
import { useTranslations } from "next-intl";
import { ArrowUpRight, ArrowDownRight, Activity } from "lucide-react";
import Link from "next/link";
import { cn, fmtMoney } from "@/lib/utils";
import type { ActivityItem } from "@/lib/dashboard";

function shortHash(s: string | null | undefined): string {
  if (!s) return "—";
  return s.length > 14 ? `${s.slice(0, 6)}…${s.slice(-4)}` : s;
}

export function RecentActivity({ data, loading }: { data: ActivityItem[]; loading?: boolean }) {
  const t = useTranslations("admin.recent_activity");

  const relTime = (iso: string): string => {
    const ts = new Date(iso).getTime();
    if (isNaN(ts)) return "—";
    const diff = (Date.now() - ts) / 1000;
    if (diff < 60)        return t("ago_s", { n: Math.floor(diff) });
    if (diff < 3600)      return t("ago_m", { n: Math.floor(diff / 60) });
    if (diff < 86400)     return t("ago_h", { n: Math.floor(diff / 3600) });
    if (diff < 86400 * 30) return t("ago_d", { n: Math.floor(diff / 86400) });
    return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "2-digit" });
  };

  return (
    <section
      className="prosper-card overflow-hidden"
      data-testid="recent-activity"
    >
      <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-surface">
        <div>
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
            {t("live")}
          </div>
          <h3 className="font-display font-bold text-sm text-fg mt-0.5 flex items-center gap-1.5">
            <Activity size={14} /> {t("title")}
          </h3>
        </div>
        <Link
          href="/admin/operations"
          className="text-[10px] font-mono uppercase tracking-wider text-primary hover:underline"
        >
          {t("all")} →
        </Link>
      </div>

      {loading && !data?.length ? (
        <div className="p-3 space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-10 rounded bg-surface-hover animate-pulse" />
          ))}
        </div>
      ) : data.length === 0 ? (
        <div className="p-6 text-center text-xs text-fg-subtle font-mono">{t("empty")}</div>
      ) : (
        <ul>
          {data.slice(0, 8).map((it) => {
            const isSub = it.type === "subscribe";
            return (
              <li
                key={it.tx_id}
                data-testid={`activity-row-${it.tx_id}`}
                className="px-4 py-2.5 border-b border-border last:border-0 hover:bg-surface-hover transition-colors"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <span
                      className={cn(
                        "inline-flex w-5 h-5 items-center justify-center rounded",
                        isSub
                          ? "bg-[color-mix(in_srgb,#0FA958_14%,transparent)] text-success"
                          : "bg-[color-mix(in_srgb,#E07B00_14%,transparent)] text-warning",
                      )}
                      title={it.type}
                    >
                      {isSub ? <ArrowUpRight size={11} /> : <ArrowDownRight size={11} />}
                    </span>
                    <div className="min-w-0">
                      <div className="text-xs text-fg truncate">{it.org_name}</div>
                      <div className="text-[10px] font-mono text-fg-subtle">
                        {shortHash(it.prosper_tx_id)} · {relTime(it.created_at)}
                      </div>
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <div className={cn(
                      "font-mono text-xs font-semibold tabular",
                      isSub ? "text-success" : "text-warning",
                    )}>
                      {isSub ? "+" : "−"}{fmtMoney(it.amount)}
                    </div>
                    <div className="text-[10px] font-mono text-fg-subtle uppercase tracking-wider">
                      {it.type}
                    </div>
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
