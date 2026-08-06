"use client";
/**
 * YieldChart — per-asset monthly yield (P2 Feb 2026).
 *
 * Toma una serie por moneda y deja al consumidor elegir qué carril mostrar
 * (ARSa o USDC). No agregamos: el principio del portal es no mezclar
 * monedas en un mismo número, así que el toggle simplemente cambia el
 * dataset visible y la unidad del eje Y.
 */
import {
  ResponsiveContainer, AreaChart, Area, XAxis, YAxis,
  CartesianGrid, Tooltip,
} from "recharts";

export interface YieldPoint {
  month: string;
  arsa:  number;
  usdc:  number;
}

type Asset = "arsa" | "usdc";

const COLORS: Record<Asset, { stroke: string; gradientId: string }> = {
  arsa: { stroke: "#0EA5E9", gradientId: "yield-fill-arsa" },
  usdc: { stroke: "#22C55E", gradientId: "yield-fill-usdc" },
};

const UNIT: Record<Asset, string> = { arsa: "ARSa", usdc: "USDC" };

function fmtAxis(v: number, asset: Asset): string {
  const symbol = asset === "arsa" ? "" : "$";
  if (Math.abs(v) >= 1_000_000) return `${symbol}${(v / 1_000_000).toFixed(1)}M`;
  if (Math.abs(v) >= 1_000)     return `${symbol}${(v / 1_000).toFixed(1)}k`;
  return `${symbol}${v.toFixed(0)}`;
}

function fmtTooltip(v: number, asset: Asset): string {
  const n = v.toLocaleString("es-AR",
    { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${n} ${UNIT[asset]}`;
}

export function YieldChart({
  data, asset, height = 220,
}: {
  data: YieldPoint[];
  asset: Asset;
  height?: number;
}) {
  const c = COLORS[asset];
  return (
    <div className="w-full" data-testid={`yield-chart-${asset}`}>
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={data} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id={c.gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%"   stopColor={c.stroke} stopOpacity={0.32} />
              <stop offset="100%" stopColor={c.stroke} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--border))" vertical={false} />
          <XAxis
            dataKey="month"
            tickFormatter={(v: string) => v.slice(5) + "/" + v.slice(2, 4)}
            tick={{ fontSize: 10, fontFamily: "var(--font-plex-mono)",
                     fill: "rgb(var(--fg-subtle))" }}
            tickLine={false} axisLine={false} minTickGap={16}
          />
          <YAxis
            tickFormatter={(v: number) => fmtAxis(v, asset)}
            tick={{ fontSize: 10, fontFamily: "var(--font-plex-mono)",
                     fill: "rgb(var(--fg-subtle))" }}
            tickLine={false} axisLine={false} width={56}
          />
          <Tooltip
            contentStyle={{
              background: "rgb(var(--surface))",
              border: "1px solid rgb(var(--border))",
              borderRadius: 8, fontSize: 12,
              fontFamily: "var(--font-plex-mono)",
            }}
            formatter={(v: number) => [fmtTooltip(v, asset),
                                          `Yield ${UNIT[asset]}`]}
            labelStyle={{ color: "rgb(var(--fg-muted))" }}
          />
          <Area
            type="monotone"
            dataKey={asset}
            stroke={c.stroke}
            strokeWidth={2}
            fill={`url(#${c.gradientId})`}
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
