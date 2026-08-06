"use client";
import {
  ResponsiveContainer, AreaChart, Area, XAxis, YAxis,
  CartesianGrid, Tooltip,
} from "recharts";
import type { NavPoint } from "@/lib/dashboard";

export function NavChart({ data, height = 240 }: { data: NavPoint[]; height?: number }) {
  return (
    <div className="w-full" data-testid="nav-chart">
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={data} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="nav-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#2B6BFF" stopOpacity={0.28} />
              <stop offset="100%" stopColor="#2B6BFF" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--border))" vertical={false} />
          <XAxis
            dataKey="date"
            tickFormatter={(v: string) => v.slice(5)}
            tick={{ fontSize: 10, fontFamily: "var(--font-plex-mono)", fill: "rgb(var(--fg-subtle))" }}
            tickLine={false}
            axisLine={false}
            minTickGap={28}
          />
          <YAxis
            domain={[(dataMin: number) => +(dataMin - 0.002).toFixed(4), (dataMax: number) => +(dataMax + 0.002).toFixed(4)]}
            tickFormatter={(v: number) => v.toFixed(4)}
            tick={{ fontSize: 10, fontFamily: "var(--font-plex-mono)", fill: "rgb(var(--fg-subtle))" }}
            tickLine={false}
            axisLine={false}
            width={56}
          />
          <Tooltip
            contentStyle={{
              background: "rgb(var(--surface))",
              border: "1px solid rgb(var(--border))",
              borderRadius: 8,
              fontSize: 12,
              fontFamily: "var(--font-plex-mono)",
            }}
            formatter={(v: number) => [v.toFixed(6), "NAV"]}
            labelStyle={{ color: "rgb(var(--fg-muted))" }}
          />
          <Area
            type="monotone"
            dataKey="nav"
            stroke="#2B6BFF"
            strokeWidth={2}
            fill="url(#nav-fill)"
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
