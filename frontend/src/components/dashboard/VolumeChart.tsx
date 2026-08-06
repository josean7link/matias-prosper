"use client";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis,
  CartesianGrid, Tooltip, Legend,
} from "recharts";
import type { VolumePoint } from "@/lib/dashboard";

const fmtCompact = (v: number) => {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`;
  return `$${v}`;
};

export function VolumeChart({ data, height = 240 }: { data: VolumePoint[]; height?: number }) {
  return (
    <div className="w-full" data-testid="volume-chart">
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--border))" vertical={false} />
          <XAxis
            dataKey="date"
            tickFormatter={(v: string) => v.slice(5)}
            tick={{ fontSize: 10, fontFamily: "var(--font-plex-mono)", fill: "rgb(var(--fg-subtle))" }}
            tickLine={false}
            axisLine={false}
            minTickGap={20}
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
            formatter={(v: number, key: string) => [fmtCompact(Number(v)), key]}
            labelStyle={{ color: "rgb(var(--fg-muted))" }}
          />
          <Legend
            wrapperStyle={{ fontSize: 10, fontFamily: "var(--font-plex-mono)", textTransform: "uppercase", letterSpacing: "0.1em" }}
            iconSize={8}
            iconType="square"
          />
          <Bar dataKey="subscribe" stackId="vol" fill="#0FA958" radius={[2, 2, 0, 0]} />
          <Bar dataKey="redeem"    stackId="vol" fill="#E07B00" radius={[2, 2, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
