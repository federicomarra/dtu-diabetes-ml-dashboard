"use client";

import { useState, useEffect } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import type { TimeInRange } from "@/models/types";
import { useGlucoseUnit } from "@/controllers/GlucoseUnitContext";
import { convertGlucose, formatGlucose } from "@/models/glucoseUnits";
import {
  VERY_LOW_THRESHOLD,
  LOW_THRESHOLD,
  HIGH_THRESHOLD,
  VERY_HIGH_THRESHOLD,
} from "@/models/glucoseConfig";
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

type ViewMode = "unified" | "divided";

// ─── Unified view ──────────────────────────────────────────

interface UnifiedViewProps {
  tir: TimeInRange;
}

function pctToMinutes(pct: number): string {
  const totalMinutes = Math.round((pct / 100) * 24 * 60);
  const h = Math.floor(totalMinutes / 60);
  const m = totalMinutes % 60;
  if (h === 0) return `${m}min.`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}min.`;
}

function UnifiedView({ tir }: UnifiedViewProps) {
  const { unit } = useGlucoseUnit();

  const ranges = [
    {
      key: "very_high" as const,
      label: "Very High",
      pct: tir.very_high_pct,
      color: RANGE_COLORS.very_high,
      // above VERY_HIGH_THRESHOLD
      rangeLabel: `>${formatGlucose(VERY_HIGH_THRESHOLD, unit)}`,
    },
    {
      key: "high" as const,
      label: "High",
      pct: tir.high_pct,
      color: RANGE_COLORS.high,
      rangeLabel: `${formatGlucose(HIGH_THRESHOLD, unit)} – ${formatGlucose(VERY_HIGH_THRESHOLD, unit)}`,
    },
    {
      key: "in_range" as const,
      label: "In Range",
      pct: tir.in_range_pct,
      color: RANGE_COLORS.in_range,
      rangeLabel: `${formatGlucose(LOW_THRESHOLD, unit)} – ${formatGlucose(HIGH_THRESHOLD, unit)}`,
    },
    {
      key: "low" as const,
      label: "Low",
      pct: tir.low_pct,
      color: RANGE_COLORS.low,
      rangeLabel: `${formatGlucose(VERY_LOW_THRESHOLD, unit)} – ${formatGlucose(LOW_THRESHOLD, unit)}`,
    },
    {
      key: "very_low" as const,
      label: "Very Low",
      pct: tir.very_low_pct,
      color: RANGE_COLORS.very_low,
      rangeLabel: `<${formatGlucose(VERY_LOW_THRESHOLD, unit)}`,
    },
  ];

  // The threshold values displayed on the left axis (top → bottom order in CSS)
  const thresholdLabels = [
    { value: VERY_HIGH_THRESHOLD, after: "very_high" },
    { value: HIGH_THRESHOLD, after: "high" },
    { value: LOW_THRESHOLD, after: "in_range" },
    { value: VERY_LOW_THRESHOLD, after: "low" },
  ];

  // cumulative offset from the top for each segment (top = very_high)
  const offsets: Record<string, number> = {};
  let cumulative = 0;
  for (const r of ranges) {
    offsets[r.key] = cumulative;
    cumulative += r.pct;
  }

  // Entrance animation: bar starts all-green, then morphs to real proportions.
  // Because the sum of heights is always 100%, the bar stays full throughout.
  const [animated, setAnimated] = useState(false);
  useEffect(() => {
    const raf = requestAnimationFrame(() => setAnimated(true));
    return () => cancelAnimationFrame(raf);
  }, []);

  const segmentHeight = (key: string, pct: number) => {
    if (!animated) return key === "in_range" ? "100%" : "0%";
    return `${pct}%`;
  };

  return (
    <div className={styles.unifiedWrapper}>
      {/* Left axis: threshold labels */}
      <div className={styles.unifiedAxis} style={{ opacity: animated ? 1 : 0, transition: "opacity 0.5s ease 0.55s" }}>
        {thresholdLabels.map(({ value, after }) => (
          <div
            key={value}
            className={styles.axisLabel}
            style={{
              top: `${offsets[after] + (
                ranges.find(r => r.key === after)!.pct
              )}%`
            }}
          >
            {convertGlucose(value, unit)}
          </div>
        ))}
      </div>

      {/* Stacked bar */}
      <div className={styles.unifiedBar}>
        {ranges.map((r) => (
          <div
            key={r.key}
            className={styles.unifiedSegment}
            style={{
              height: segmentHeight(r.key, r.pct),
              background: r.color,
              minHeight: animated && r.pct > 0 ? 4 : 0,
            }}
            title={`${r.label}: ${r.pct}%`}
          />
        ))}

        {/* Threshold tick lines overlaid on the bar */}
        {thresholdLabels.map(({ value, after }) => {
          const top = offsets[after] + ranges.find(r => r.key === after)!.pct;
          return (
            <div
              key={value}
              className={styles.tickLine}
              style={{
                top: `${top}%`,
                opacity: animated ? 1 : 0,
                transition: "opacity 0.5s ease 0.55s",
              }}
            />
          );
        })}
      </div>

      {/* Right legend */}
      <div
        className={styles.unifiedLegend}
        style={{ opacity: animated ? 1 : 0, transition: "opacity 0.5s ease 0.55s" }}
      >
        {ranges.map((r) => (
          <div
            key={r.key}
            className={styles.legendRow}
            style={{ height: `${r.pct}%`, minHeight: r.pct > 0 ? 32 : 0 }}
          >
            <div className={styles.legendDivider} />
            <div className={styles.legendContent}>
              <span className={styles.legendName} style={{ color: r.color }}>{r.label}</span>
              <span className={styles.legendRange}>{r.rangeLabel}</span>
            </div>
            <div className={styles.legendStats}>
              <span className={styles.legendPct}>{r.pct.toFixed(1)}%</span>
              <span className={styles.legendTime}>({pctToMinutes(r.pct)})</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Divided view (original) ───────────────────────────────

function DividedView({ tir }: { tir: TimeInRange }) {
  const data = [
    { name: "Very Low", pct: tir.very_low_pct, key: "very_low" as const },
    { name: "Low", pct: tir.low_pct, key: "low" as const },
    { name: "In Range", pct: tir.in_range_pct, key: "in_range" as const },
    { name: "High", pct: tir.high_pct, key: "high" as const },
    { name: "Very High", pct: tir.very_high_pct, key: "very_high" as const },
  ];

  return (
    <ResponsiveContainer width="100%" height="100%">
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
  );
}

// ─── Main component ────────────────────────────────────────

export default function TIRBarChart({ tir }: TIRBarChartProps) {
  const [mode, setMode] = useState<ViewMode>("unified");

  return (
    <div className={styles.container}>
      {/* Header row */}
      <div className={styles.header}>
        <div>
          <h3 className={styles.title}>Time in Range</h3>
          <div className={styles.totalReadings}>
            {tir.total_readings.toLocaleString()} readings
          </div>
        </div>

        {/* Mode switcher */}
        <div className={styles.switcher}>
          <button
            className={`${styles.switchBtn} ${mode === "unified" ? styles.switchBtnActive : ""}`}
            onClick={() => setMode("unified")}
          >
            unified
          </button>
          <button
            className={`${styles.switchBtn} ${mode === "divided" ? styles.switchBtnActive : ""}`}
            onClick={() => setMode("divided")}
          >
            divided
          </button>
        </div>
      </div>

      {/* Chart — fixed-height wrapper keeps the card size stable on toggle */}
      <div className={styles.chartArea}>
        {mode === "unified" ? (
          <UnifiedView tir={tir} />
        ) : (
          <DividedView tir={tir} />
        )}
      </div>

      {/* Target indicator */}
      <div className={styles.target}>
        <span
          className={styles.targetDot}
          style={{
            background:
              tir.in_range_pct >= 70 ? "var(--success)" : "var(--warning)",
          }}
        />
        TIR Target: ≥70% — Current: {tir.in_range_pct}%
      </div>
    </div>
  );
}
