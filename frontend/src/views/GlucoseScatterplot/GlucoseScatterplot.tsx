"use client";

import { useState, useEffect } from "react";
import {
  ComposedChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  ErrorBar,
} from "recharts";
import type { DailyGlucosePoint } from "@/models/types";
import { useGlucoseUnit } from "@/controllers/GlucoseUnitContext";
import { useGlucoseRanges } from "@/controllers/GlucoseRangesContext";
import { convertGlucose, formatGlucose } from "@/models/glucoseUnits";
import type { GlucoseUnit } from "@/models/glucoseUnits";
import styles from "./GlucoseScatterplot.module.css";

// --- Types ---

type ViewMode = "scientific" | "modern";

interface ChartPoint {
  date: string;
  displayDate: string;
  avg: number;
  min: number;
  max: number;
  errorUp: number;
  errorDown: number;
}

interface Props {
  points: DailyGlucosePoint[];
  patientId: number;
}

// --- Helpers ---

function formatDate(dateStr: string): string {
  const d = new Date(dateStr + "T00:00:00Z");
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

function toDisplayPts(points: DailyGlucosePoint[], unit: GlucoseUnit): ChartPoint[] {
  return points.map((p) => {
    const avg = convertGlucose(p.average, unit);
    const min = convertGlucose(p.min, unit);
    const max = convertGlucose(p.max, unit);
    return {
      date: p.date,
      displayDate: formatDate(p.date),
      avg,
      min,
      max,
      errorUp: Math.max(0, max - avg),
      errorDown: Math.max(0, avg - min),
    };
  });
}

// --- Custom dot shapes ---

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function ScientificDot(props: any) {
  const { cx, cy } = props;
  return (
    <circle cx={cx} cy={cy} r={4} fill="#27ae60" stroke="var(--card-bg)" strokeWidth={1.5} />
  );
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function ModernDot(props: any) {
  const { cx, cy } = props;
  return (
    <circle cx={cx} cy={cy} r={6} fill="#27ae60" stroke="var(--card-bg)" strokeWidth={2} />
  );
}

// --- Custom tooltip ---

interface ScatterTooltipProps {
  active?: boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  payload?: any[];
  unit: GlucoseUnit;
}

function ScatterTooltip({ active, payload, unit }: ScatterTooltipProps) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload as ChartPoint;
  return (
    <div className={styles.tooltip}>
      <div className={styles.tooltipDate}>{p.displayDate}</div>
      <div className={styles.tooltipRow}>
        <span className={styles.tooltipLabel}>Avg</span>
        <span className={styles.tooltipVal}>{p.avg.toFixed(1)} {unit}</span>
      </div>
      <div className={styles.tooltipRow}>
        <span className={styles.tooltipLabel}>Max</span>
        <span className={styles.tooltipVal}>{p.max.toFixed(1)} {unit}</span>
      </div>
      <div className={styles.tooltipRow}>
        <span className={styles.tooltipLabel}>Min</span>
        <span className={styles.tooltipVal}>{p.min.toFixed(1)} {unit}</span>
      </div>
    </div>
  );
}

// --- Main component ---

export default function GlucoseScatterplot({ points }: Props) {
  const { unit } = useGlucoseUnit();
  const { ranges: thresholds } = useGlucoseRanges();
  const [mode, setMode] = useState<ViewMode>("modern");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const raf = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(raf);
  }, []);

  const chartData = toDisplayPts(points, unit);

  const vl = convertGlucose(thresholds.veryLow, unit);
  const l = convertGlucose(thresholds.low, unit);
  const h = convertGlucose(thresholds.high, unit);
  const vh = convertGlucose(thresholds.veryHigh, unit);

  const allVals = chartData.flatMap((p) => [p.min, p.avg, p.max]);
  const yMin = allVals.length ? Math.min(...allVals, vl) : 0;
  const yMax = allVals.length ? Math.max(...allVals, vh) : 20;
  const pad = (yMax - yMin) * 0.15;
  const domain: [number, number] = [
    Math.max(0, Math.floor((yMin - pad) * 10) / 10),
    Math.ceil((yMax + pad) * 10) / 10,
  ];

  const thresholdLines = [
    { value: vl, color: "#c0392b", label: "VL " + formatGlucose(thresholds.veryLow, unit) },
    { value: l, color: "#e67e22", label: "L  " + formatGlucose(thresholds.low, unit) },
    { value: h, color: "#f39c12", label: "H  " + formatGlucose(thresholds.high, unit) },
    { value: vh, color: "#e74c3c", label: "VH " + formatGlucose(thresholds.veryHigh, unit) },
  ];

  const isEmpty = chartData.length === 0;

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div>
          <h3 className={styles.title}>Daily Glucose Averages</h3>
          <p className={styles.subtitle}>Average, min and max per day ({unit})</p>
        </div>

        <div className={styles.switcher}>
          <button
            className={styles.switchBtn + (mode === "modern" ? " " + styles.switchBtnActive : "")}
            onClick={() => setMode("modern")}
          >
            Modern
          </button>
          <button
            className={styles.switchBtn + (mode === "scientific" ? " " + styles.switchBtnActive : "")}
            onClick={() => setMode("scientific")}
          >
            Scientific
          </button>
        </div>
      </div>

      <div className={styles.chartArea}>
        {isEmpty ? (
          <div className={styles.empty}>No glucose data for this period.</div>
        ) : !mounted ? null : (
          <ResponsiveContainer width="100%" height="100%" minHeight={280} minWidth={0} debounce={50}>
            <ComposedChart data={chartData} margin={{ top: 8, right: 24, bottom: 8, left: 0 }}>
              <CartesianGrid stroke="var(--border)" strokeDasharray="4 4" strokeOpacity={0.4} />
              <XAxis
                dataKey="displayDate"
                tick={{ fontSize: 11, fill: "var(--text-secondary)" }}
                tickLine={false}
                axisLine={{ stroke: "var(--border)" }}
                interval="preserveStartEnd"
              />
              <YAxis
                domain={domain}
                tick={{ fontSize: 11, fill: "var(--text-secondary)" }}
                tickLine={false}
                axisLine={false}
                width={42}
              />

              {thresholdLines.map((t) => (
                <ReferenceLine
                  key={t.value}
                  y={t.value}
                  stroke={t.color}
                  strokeDasharray="6 3"
                  strokeOpacity={0.7}
                  label={{ value: t.label, position: "insideTopRight", fontSize: 9, fill: t.color, dy: -4 }}
                />
              ))}

              <Tooltip
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                content={(props: any) => <ScatterTooltip {...props} unit={unit} />}
                cursor={{ stroke: "var(--border)", strokeWidth: 1 }}
              />

              {mode === "scientific" ? (
                <Scatter dataKey="avg" fill="#27ae60" shape={<ScientificDot />}>
                  <ErrorBar dataKey="errorUp" width={5} strokeWidth={1.5} stroke="#27ae60" direction="y" />
                  <ErrorBar dataKey="errorDown" width={5} strokeWidth={1.5} stroke="#27ae60" direction="y" />
                </Scatter>
              ) : (
                <Scatter dataKey="avg" fill="#27ae60" shape={<ModernDot />}>
                  <ErrorBar dataKey="errorUp" width={12} strokeWidth={10} stroke="#27ae60" strokeOpacity={0.22} direction="y" />
                  <ErrorBar dataKey="errorDown" width={12} strokeWidth={10} stroke="#27ae60" strokeOpacity={0.22} direction="y" />
                </Scatter>
              )}
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className={styles.legend}>
        <svg width="10" height="10">
          <circle cx="5" cy="5" r="5" fill="#27ae60" />
        </svg>
        <span className={styles.legendText}>Daily average</span>
        <svg width="10" height="16">
          <rect x="1" y="0" width="8" height="16" rx="4" fill="#27ae60" fillOpacity={0.25} />
        </svg>
        <span className={styles.legendText}>Min - Max range</span>
      </div>
    </div>
  );
}
