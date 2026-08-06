"use client";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis,
  CartesianGrid, Tooltip,
} from "recharts";
import type { RevenuePoint } from "@/lib/dashboard";

const fmtCompact = (v: number) => {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(1)}K`;
  return `$${v.toFixed(0)}`;
};

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

export function RevenueChart({ data, height = 240 }: { data: RevenuePoint[]; height?: number }) {
  // "2026-05" -> "May 26"
  const enriched = data.map((d) => {
    const [y, m] = d.month.split("-");
    return { ...d, label: `${MONTHS[parseInt(m, 10) - 1]} ${y.slice(2)}` };
  });
  return (
    <div className="w-full" data-testid="revenue-chart">
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={enriched} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--border))" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fontSize: 10, fontFamily: "var(--font-plex-mono)", fill: "rgb(var(--fg-subtle))" }}
            tickLine={false}
            axisLine={false}
            minTickGap={4}
          />
          <YAxis
            tickFormatter={fmtCompact}
            tick={{ fontSize: 10, fontFamily: "var(--font-plex-mono)", fill: "rgb(var(--fg-subtle))" }}
            tickLine={false}
            axisLine={false}
            width={52}
          />
          <Tooltip
            cursor={{ fill: "rgba(43,107,255,0.06)" }}
            contentStyle={{
              background: "rgb(var(--surface))",
              border: "1px solid rgb(var(--border))",
              borderRadius: 8,
              fontSize: 12,
              fontFamily: "var(--font-plex-mono)",
            }}
            formatter={(v: number) => [fmtCompact(Number(v)), "Revenue"]}
            labelStyle={{ color: "rgb(var(--fg-muted))" }}
          />
          <Bar dataKey="revenue" fill="#2B6BFF" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
