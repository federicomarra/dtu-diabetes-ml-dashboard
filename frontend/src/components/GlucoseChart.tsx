"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ReferenceArea,
  ResponsiveContainer,
} from "recharts";
import { format } from "date-fns";
import type { GlucoseReading } from "@/types";
import styles from "./GlucoseChart.module.css";

interface GlucoseChartProps {
  readings: GlucoseReading[];
  title?: string;
}

export default function GlucoseChart({
  readings,
  title = "Glucose Trace",
}: GlucoseChartProps) {
  const chartData = readings
    .slice()
    .sort(
      (a, b) =>
        new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
    )
    .map((r) => ({
      time: format(new Date(r.timestamp), "HH:mm"),
      fullTime: format(new Date(r.timestamp), "MMM d, HH:mm"),
      glucose: r.glucose_mmoll,
      status: r.status,
    }));

  return (
    <div className={styles.container}>
      <h3 className={styles.title}>{title}</h3>
      <ResponsiveContainer width="100%" height={320}>
        <LineChart data={chartData} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />

          {/* Target range shading (3.9–10.0 mmol/L) */}
          <ReferenceArea
            y1={3.9}
            y2={10.0}
            fill="var(--success)"
            fillOpacity={0.08}
          />

          {/* Clinical threshold lines */}
          <ReferenceLine
            y={3.9}
            stroke="var(--warning)"
            strokeDasharray="4 4"
            label={{ value: "3.9", position: "left", fontSize: 11 }}
          />
          <ReferenceLine
            y={10.0}
            stroke="var(--warning)"
            strokeDasharray="4 4"
            label={{ value: "10.0", position: "left", fontSize: 11 }}
          />
          <ReferenceLine
            y={13.9}
            stroke="var(--danger)"
            strokeDasharray="4 4"
            label={{ value: "13.9", position: "left", fontSize: 11 }}
          />

          <XAxis
            dataKey="time"
            tick={{ fontSize: 11 }}
            interval="preserveStartEnd"
          />
          <YAxis
            domain={[2.2, 19.4]}
            tick={{ fontSize: 11 }}
            label={{
              value: "mmol/L",
              angle: -90,
              position: "insideLeft",
              fontSize: 12,
            }}
          />
          <Tooltip
            contentStyle={{
              background: "var(--card-bg)",
              border: "1px solid var(--border)",
              borderRadius: "8px",
            }}
            formatter={(value: unknown) => [`${value} mmol/L`, "Glucose"]}
            labelFormatter={(label: unknown) => `Time: ${label}`}
          />
          <Line
            type="monotone"
            dataKey="glucose"
            stroke="var(--primary)"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, fill: "var(--primary)" }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
