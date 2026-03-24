"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import type { TimeInRange } from "@/types";
import styles from "./TIRBarChart.module.css";

interface TIRBarChartProps {
  tir: TimeInRange;
}

const RANGE_COLORS = {
  very_low: "#c0392b",
  low: "#e67e22",
  in_range: "#27ae60",
  high: "#f39c12",
  very_high: "#e74c3c",
};

const RANGE_LABELS = {
  very_low: "Very Low (<54)",
  low: "Low (54–69)",
  in_range: "In Range (70–180)",
  high: "High (181–250)",
  very_high: "Very High (>250)",
};

export default function TIRBarChart({ tir }: TIRBarChartProps) {
  const data = [
    { name: "Very Low", pct: tir.very_low_pct, key: "very_low" as const },
    { name: "Low", pct: tir.low_pct, key: "low" as const },
    { name: "In Range", pct: tir.in_range_pct, key: "in_range" as const },
    { name: "High", pct: tir.high_pct, key: "high" as const },
    { name: "Very High", pct: tir.very_high_pct, key: "very_high" as const },
  ];

  return (
    <div className={styles.container}>
      <h3 className={styles.title}>Time in Range</h3>
      <div className={styles.totalReadings}>
        {tir.total_readings.toLocaleString()} readings
      </div>

      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} layout="vertical" margin={{ left: 80 }}>
          <XAxis type="number" domain={[0, 100]} unit="%" tick={{ fontSize: 11 }} />
          <YAxis
            type="category"
            dataKey="name"
            tick={{ fontSize: 11 }}
            width={80}
          />
          <Tooltip
            formatter={(value: unknown) => [`${value}%`, "Percentage"]}
            contentStyle={{
              background: "var(--card-bg)",
              border: "1px solid var(--border)",
              borderRadius: "8px",
            }}
          />
          <Bar dataKey="pct" radius={[0, 4, 4, 0]}>
            {data.map((entry) => (
              <Cell key={entry.key} fill={RANGE_COLORS[entry.key]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      {/* Target indicator */}
      <div className={styles.target}>
        <span
          className={styles.targetDot}
          style={{
            background:
              tir.in_range_pct >= 70
                ? "var(--success)"
                : "var(--warning)",
          }}
        />
        TIR Target: ≥70% — Current: {tir.in_range_pct}%
      </div>
    </div>
  );
}
