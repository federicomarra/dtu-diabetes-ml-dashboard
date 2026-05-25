"use client";

import { useState, useEffect, ReactNode } from "react";
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
import styles from "./TIRChart.module.css";

interface TIRChartProps {
  tir: TimeInRange;
}

const RANGE_COLORS = {
  very_low: "#c0392b",
  low: "#e67e22",
  in_range: "#27ae60",
  high: "#f39c12",
  very_high: "#e74c3c",
};

type ViewMode = "stacked" | "barchart";

function returnTextFromSpanDays(days: number): ReactNode {
  let span: string;
  if (days < 1) {
    span = "day";
  } else if (days === 7) {
    span = "week";
  } else if (days < 14) {
    span = `${days} days`;
  } else if (days === 30 || days === 31) {
    span = "month";
  } else if (days < 30) {
    span = `${Math.round(days / 7)} weeks`;
  } else if (days < 365) {
    span = `${Math.round(days / 30)} months`;
  } else {
    span = `${Math.round(days / 365)} year${Math.round(days / 365) !== 1 ? "s" : ""}`;
  }
  let start_day: string = new Date(Date.now() - days * 24 * 60 * 60 * 1000).toLocaleDateString().split("/").slice(0, -1).join("/");
  let end_day: string = new Date().toLocaleDateString().split("/").slice(0, -1).join("/");
  return (
    <div className={styles.temporalSpan}>
      <strong>latest {span}</strong>
      <br />
      ({start_day} - {end_day})
    </div>
  );
}

// ─── Stacked view ──────────────────────────────────────────

interface StackedViewProps {
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

function StackedView({ tir }: StackedViewProps) {
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
    <div className={styles.stackedWrapper}>
      {/* Left axis: threshold labels */}
      <div className={styles.stackedAxis} style={{ opacity: animated ? 1 : 0, transition: "opacity 0.5s ease 0.55s" }}>
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
      <div className={styles.stackedBar}>
        {ranges.map((r) => (
          <div
            key={r.key}
            className={styles.stackedSegment}
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
        className={styles.stackedLegend}
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

// ─── BarChart view (original) ───────────────────────────────

function BarChartView({ tir }: { tir: TimeInRange }) {
  const data = [
    { name: "Very Low", pct: tir.very_low_pct, key: "very_low" as const },
    { name: "Low", pct: tir.low_pct, key: "low" as const },
    { name: "In Range", pct: tir.in_range_pct, key: "in_range" as const },
    { name: "High", pct: tir.high_pct, key: "high" as const },
    { name: "Very High", pct: tir.very_high_pct, key: "very_high" as const },
  ];

  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} layout="vertical" margin={{ left: 0 }}>
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

export default function TIRChart({ tir }: TIRChartProps) {
  const [mode, setMode] = useState<ViewMode>("stacked");

  return (
    <div className={styles.container}>
      {/* Header row */}
      <div className={styles.header}>
        <div>
          <h3 className={styles.title}>Time in Range</h3>
          <div className={styles.temporalSpan}>
            {returnTextFromSpanDays(tir.temporal_span_days)}
          </div>
        </div>

        {/* Mode switcher */}
        <div className={styles.switcher}>
          <button
            className={`${styles.switchBtn} ${mode === "stacked" ? styles.switchBtnActive : ""}`}
            onClick={() => setMode("stacked")}
          >
            Stacked
          </button>
          <button
            className={`${styles.switchBtn} ${mode === "barchart" ? styles.switchBtnActive : ""}`}
            onClick={() => setMode("barchart")}
          >
            BarChart
          </button>
        </div>
      </div>

      {/* Chart — fixed-height wrapper keeps the card size stable on toggle */}
      <div className={styles.chartArea}>
        {mode === "stacked" ? (
          <StackedView tir={tir} />
        ) : (
          <BarChartView tir={tir} />
        )}
      </div>

      {/* Target indicator */}
      <div className={styles.target} style={{
        color:
          tir.in_range_pct >= 70 ? "var(--success)" : "var(--warning)",
      }}>
        TIR Target: ≥70% | Current: {tir.in_range_pct}%
        <span
          className={styles.targetDot}
          style={{
            color:
              tir.in_range_pct >= 70 ? "var(--success)" : "var(--warning)",
          }}
        />
      </div>
    </div>
  );
}
