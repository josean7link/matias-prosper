"use client";
import { useEffect, useState, useRef } from "react";
import { TrendingUp, Sparkles, Zap } from "lucide-react";
import {
  ResponsiveContainer, AreaChart, Area, Tooltip, YAxis,
} from "recharts";
import { fmtUsd } from "@/lib/client-portal";

interface Props {
  earned: number;
  earningNow: number;
  total: number;
  asOf: string;
  series: Array<{ date: string; yield_usd: number }>;
}

/**
 * Inline "hoy ganaste +$X.XX" widget for the client dashboard.
 *
 * Two behaviours:
 *  - Counter animates from `earned` up to `total` over ~600ms when the panel
 *    first mounts (the "wow" moment).
 *  - Once mounted, the live portion (`earningNow`) ticks up every 200ms so the
 *    user sees the number breathe — gives the "money working" feeling without
 *    re-hitting the API.
 */
export function TodayYieldCard({ earned, earningNow, total, asOf, series }: Props) {
  const [displayed, setDisplayed] = useState(earned);
  const targetRef = useRef(total);
  targetRef.current = total;

  // Animate from `earned` -> `total` once on mount
  useEffect(() => {
    const start = performance.now();
    const from = earned;
    const to = total;
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

  // Live tick — only when there's something earning right now
  useEffect(() => {
    if (earningNow <= 0) return;
    // earningNow is per-day; per-tick = perDay / (24*60*60*5) for 200ms ticks
    const perTick = earningNow / (24 * 60 * 60 * 5);
    const id = setInterval(() => {
      setDisplayed((d) => d + perTick);
    }, 200);
    return () => clearInterval(id);
  }, [earningNow]);

  const hasYield = total > 0;

  return (
    <div
      className="prosper-card p-5 mb-6 relative overflow-hidden"
      data-testid="today-yield-card"
    >
      {/* subtle gradient */}
      <div className="absolute inset-0 bg-gradient-to-br from-success/8 via-transparent to-primary/5
                       pointer-events-none" />
      {/* grain accent on the right */}
      <div className="absolute right-0 top-0 h-full w-1/3 opacity-[0.04] pointer-events-none"
           style={{ background:
             "radial-gradient(circle at 100% 0%, currentColor 0%, transparent 60%)" }} />

      <div className="relative grid grid-cols-1 sm:grid-cols-[1fr_180px] gap-5 items-center">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Sparkles size={12} className="text-success" />
            <span className="text-[10px] font-mono uppercase tracking-[0.18em] text-success">
              {hasYield ? "Yield de hoy" : "Aún sin yield hoy"}
            </span>
            {earningNow > 0 && (
              <span className="ml-1 inline-flex items-center gap-1 text-[9px] font-mono uppercase
                                tracking-wider text-fg-subtle">
                <span className="h-1.5 w-1.5 rounded-full bg-success animate-pulse" />
                Activo
              </span>
            )}
          </div>

          <div className="flex items-baseline gap-2">
            <span className="text-[10px] font-mono tabular-nums text-success">+</span>
            <span
              className="text-4xl font-display font-black text-fg tabular-nums tracking-tight"
              data-testid="today-yield-amount"
            >
              {fmtUsd(displayed)}
            </span>
            <span className="text-xs font-mono text-fg-subtle">USDC</span>
          </div>

          <p className="text-xs text-fg-muted mt-1.5 max-w-md">
            {hasYield ? (
              <>
                Tus posiciones generaron este monto el {asOf}. Cuanto más
                principal invertido, más rápido crece.{" "}
                <span className="text-success font-display font-semibold">
                  Tu dinero está trabajando.
                </span>
              </>
            ) : (
              <>Hacé tu primera inversión para empezar a generar yield diariamente.</>
            )}
          </p>
        </div>

        {/* Sparkline */}
        {series.length > 0 && (
          <div className="h-16 -my-1" data-testid="today-yield-sparkline">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={series} margin={{ top: 4, right: 0, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="ty-fill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%"   stopColor="#22C55E" stopOpacity={0.45} />
                    <stop offset="100%" stopColor="#22C55E" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <YAxis hide domain={["auto", "auto"]} />
                <Tooltip
                  contentStyle={{
                    background: "rgb(var(--surface))",
                    border: "1px solid rgb(var(--border))",
                    borderRadius: 8,
                    fontSize: 11,
                    fontFamily: "var(--font-plex-mono)",
                    padding: "4px 8px",
                  }}
                  labelStyle={{ color: "rgb(var(--fg-muted))", fontSize: 9 }}
                  formatter={(v: number) => [fmtUsd(v), "Yield"]}
                  separator=" · "
                />
                <Area
                  type="monotone"
                  dataKey="yield_usd"
                  stroke="#22C55E"
                  strokeWidth={1.5}
                  fill="url(#ty-fill)"
                  dot={false}
                />
              </AreaChart>
            </ResponsiveContainer>
            <div className="text-[9px] font-mono uppercase tracking-wider text-fg-subtle text-right">
              <TrendingUp size={9} className="inline-block mr-0.5" />
              últimos 7 días
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
