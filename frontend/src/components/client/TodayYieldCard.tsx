"use client";
/**
 * TodayYieldCard — "ganaste hoy +X" celebratorio.
 *
 * P2 (Feb 2026): el card ahora vive por moneda. El consumidor decide qué
 * moneda mostrar (`asset`) y le pasa la serie de 7 días filtrada para esa
 * moneda. Sin agregados cross-currency.
 */
import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Sparkles, TrendingUp } from "lucide-react";
import {
  ResponsiveContainer, AreaChart, Area, Tooltip, YAxis,
} from "recharts";

type Asset = "arsa" | "usdc";

const COLORS: Record<Asset, { stroke: string; gradient: string }> = {
  arsa: { stroke: "#0EA5E9", gradient: "ty-fill-arsa" },
  usdc: { stroke: "#22C55E", gradient: "ty-fill-usdc" },
};
const UNIT: Record<Asset, string> = { arsa: "ARSa", usdc: "USDC" };

function fmt(v: number) {
  return v.toLocaleString(undefined,
    { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

interface Props {
  asset:       Asset;
  earned:      number;       // already accrued today
  earningNow:  number;       // per-day rate of positions that haven't accrued yet today
  total:       number;       // earned + earningNow
  asOf:        string;
  /** 7-day series, ONLY the values for this asset */
  series: Array<{ date: string; value: number }>;
}

export function TodayYieldCard({
  asset, earned, earningNow, total, asOf, series,
}: Props) {
  const t = useTranslations("dashboard.today_yield");
  const [displayed, setDisplayed] = useState(earned);
  const targetRef = useRef(total);
  targetRef.current = total;

  useEffect(() => {
    const start = performance.now();
    const from = earned, to = total;
    let raf = 0;
    const step = (t: number) => {
      const k = Math.min(1, (t - start) / 600);
      const eased = 1 - Math.pow(1 - k, 3);
      setDisplayed(from + (to - from) * eased);
      if (k < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [total]);

  useEffect(() => {
    if (earningNow <= 0) return;
    const perTick = earningNow / (24 * 60 * 60 * 5);
    const id = setInterval(() => setDisplayed((d) => d + perTick), 200);
    return () => clearInterval(id);
  }, [earningNow]);

  const c = COLORS[asset];
  const hasYield = total > 0;

  return (
    <div className="prosper-card p-5 mb-6 relative overflow-hidden"
          data-testid={`today-yield-card-${asset}`}>
      <div className="absolute inset-0 bg-gradient-to-br from-success/8 via-transparent to-primary/5
                       pointer-events-none" />
      <div className="absolute right-0 top-0 h-full w-1/3 opacity-[0.04] pointer-events-none"
            style={{ background:
              "radial-gradient(circle at 100% 0%, currentColor 0%, transparent 60%)" }} />

      <div className="relative grid grid-cols-1 sm:grid-cols-[1fr_180px] gap-5 items-center">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Sparkles size={12} className="text-success" />
            <span className="text-[10px] font-mono uppercase tracking-[0.18em] text-success">
              {hasYield ? t("label", { asset: UNIT[asset] }) : t("empty_label", { asset: UNIT[asset] })}
            </span>
            {earningNow > 0 && (
              <span className="ml-1 inline-flex items-center gap-1 text-[9px] font-mono uppercase
                                tracking-wider text-fg-subtle">
                <span className="h-1.5 w-1.5 rounded-full bg-success animate-pulse" />
                {t("live")}
              </span>
            )}
          </div>

          <div className="flex items-baseline gap-2">
            <span className="text-[10px] font-mono tabular-nums text-success">+</span>
            <span
              className="text-4xl font-display font-black text-fg tabular-nums tracking-tight"
              data-testid={`today-yield-amount-${asset}`}>
              {fmt(displayed)}
            </span>
            <span className="text-xs font-mono text-fg-subtle">{UNIT[asset]}</span>
          </div>

          <p className="text-xs text-fg-muted mt-1.5 max-w-md">
            {hasYield ? (
              <>
                {t("tagline_yield_pre", { asset: UNIT[asset], date: asOf })}{" "}
                <span className="text-success font-display font-semibold">
                  {t("tagline_working")}
                </span>
              </>
            ) : (
              <>{t("tagline_empty", { asset: UNIT[asset] })}</>
            )}
          </p>
        </div>

        {series.length > 0 && (
          <div className="h-16 -my-1" data-testid={`today-yield-sparkline-${asset}`}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={series} margin={{ top: 4, right: 0, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id={c.gradient} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%"   stopColor={c.stroke} stopOpacity={0.45} />
                    <stop offset="100%" stopColor={c.stroke} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <YAxis hide domain={["auto", "auto"]} />
                <Tooltip
                  contentStyle={{
                    background: "rgb(var(--surface))",
                    border: "1px solid rgb(var(--border))",
                    borderRadius: 8, fontSize: 11,
                    fontFamily: "var(--font-plex-mono)",
                    padding: "4px 8px",
                  }}
                  labelStyle={{ color: "rgb(var(--fg-muted))", fontSize: 9 }}
                  formatter={(v: number) => [`${fmt(v)} ${UNIT[asset]}`, "Yield"]}
                  separator=" · "
                />
                <Area type="monotone" dataKey="value"
                       stroke={c.stroke} strokeWidth={1.5}
                       fill={`url(#${c.gradient})`} dot={false} />
              </AreaChart>
            </ResponsiveContainer>
            <div className="text-[9px] font-mono uppercase tracking-wider text-fg-subtle text-right">
              <TrendingUp size={9} className="inline-block mr-0.5" />
              {t("last_seven_days")}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
