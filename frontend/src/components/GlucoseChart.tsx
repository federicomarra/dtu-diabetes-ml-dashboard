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
      glucose: r.glucose_mgdl,
      status: r.status,
    }));

  return (
    <div className={styles.container}>
      <h3 className={styles.title}>{title}</h3>
      <ResponsiveContainer width="100%" height={320}>
        <LineChart data={chartData} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />

          {/* Target range shading (70–180 mg/dL) */}
          <ReferenceArea
            y1={70}
            y2={180}
            fill="var(--success)"
            fillOpacity={0.08}
          />

          {/* Clinical threshold lines */}
          <ReferenceLine
            y={70}
            stroke="var(--warning)"
            strokeDasharray="4 4"
            label={{ value: "70", position: "left", fontSize: 11 }}
          />
          <ReferenceLine
            y={180}
            stroke="var(--warning)"
            strokeDasharray="4 4"
            label={{ value: "180", position: "left", fontSize: 11 }}
          />
          <ReferenceLine
            y={250}
            stroke="var(--danger)"
            strokeDasharray="4 4"
            label={{ value: "250", position: "left", fontSize: 11 }}
          />

          <XAxis
            dataKey="time"
            tick={{ fontSize: 11 }}
            interval="preserveStartEnd"
          />
          <YAxis
            domain={[40, 350]}
            tick={{ fontSize: 11 }}
            label={{
              value: "mg/dL",
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
            formatter={(value: unknown) => [`${value} mg/dL`, "Glucose"]}
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
