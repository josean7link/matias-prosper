"use client";
import {
  ResponsiveContainer, AreaChart, Area, XAxis, YAxis,
  CartesianGrid, Tooltip,
} from "recharts";

interface Point { month: string; yield_usd: number }

export function YieldChart({ data, height = 220 }: { data: Point[]; height?: number }) {
  return (
    <div className="w-full" data-testid="yield-chart">
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={data} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="yield-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#22C55E" stopOpacity={0.32} />
              <stop offset="100%" stopColor="#22C55E" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--border))" vertical={false} />
          <XAxis
            dataKey="month"
            tickFormatter={(v: string) => v.slice(5) + "/" + v.slice(2, 4)}
            tick={{ fontSize: 10, fontFamily: "var(--font-plex-mono)", fill: "rgb(var(--fg-subtle))" }}
            tickLine={false}
            axisLine={false}
            minTickGap={16}
          />
          <YAxis
            tickFormatter={(v: number) =>
              v >= 1000 ? `$${(v / 1000).toFixed(1)}k` : `$${v.toFixed(0)}`
            }
            tick={{ fontSize: 10, fontFamily: "var(--font-plex-mono)", fill: "rgb(var(--fg-subtle))" }}
            tickLine={false}
            axisLine={false}
            width={48}
          />
          <Tooltip
            contentStyle={{
              background: "rgb(var(--surface))",
              border: "1px solid rgb(var(--border))",
              borderRadius: 8,
              fontSize: 12,
              fontFamily: "var(--font-plex-mono)",
            }}
            formatter={(v: number) => [
              new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(v),
              "Yield",
            ]}
            labelStyle={{ color: "rgb(var(--fg-muted))" }}
          />
          <Area
            type="monotone"
            dataKey="yield_usd"
            stroke="#22C55E"
            strokeWidth={2}
            fill="url(#yield-fill)"
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
