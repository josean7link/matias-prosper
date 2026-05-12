"use client";
import {
  ResponsiveContainer, LineChart, Line, AreaChart, Area,
  XAxis, YAxis, CartesianGrid, Tooltip,
} from "recharts";

export interface MetricChartProps {
  data: Array<Record<string, number | string>>;
  xKey?: string;
  yKey?: string;
  type?: "line" | "area";
  height?: number;
  color?: string;
}

const PROSPER_BLUE = "#2B6BFF";

export function MetricChart({
  data, xKey = "x", yKey = "y", type = "area", height = 220, color = PROSPER_BLUE,
}: MetricChartProps) {
  const Chart = type === "line" ? LineChart : AreaChart;
  return (
    <div className="w-full" data-testid="metric-chart">
      <ResponsiveContainer width="100%" height={height}>
        <Chart data={data} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="prosper-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%"   stopColor={color} stopOpacity={0.25} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--border))" />
          <XAxis
            dataKey={xKey}
            stroke="rgb(var(--fg-subtle))"
            tick={{ fontSize: 10, fontFamily: "var(--font-plex-mono)" }}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            stroke="rgb(var(--fg-subtle))"
            tick={{ fontSize: 10, fontFamily: "var(--font-plex-mono)" }}
            tickLine={false}
            axisLine={false}
            width={50}
          />
          <Tooltip
            contentStyle={{
              background: "rgb(var(--surface))",
              border: "1px solid rgb(var(--border))",
              borderRadius: 8,
              fontSize: 12,
              fontFamily: "var(--font-plex-mono)",
            }}
            labelStyle={{ color: "rgb(var(--fg-muted))" }}
          />
          {type === "line" ? (
            <Line type="monotone" dataKey={yKey} stroke={color} strokeWidth={2} dot={false} />
          ) : (
            <Area type="monotone" dataKey={yKey} stroke={color} strokeWidth={2}
                  fill="url(#prosper-fill)" />
          )}
        </Chart>
      </ResponsiveContainer>
    </div>
  );
}
