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
  ReferenceArea,
  ErrorBar,
} from "recharts";
import type { DailyGlucosePoint } from "@/models/types";
import { useGlucoseUnit } from "@/controllers/GlucoseUnitContext";
import { useGlucoseRanges } from "@/controllers/GlucoseRangesContext";
import { convertGlucose } from "@/models/glucoseUnits";
import type { GlucoseUnit } from "@/models/glucoseUnits";
import styles from "./GlucoseScatterplot.module.css";

// --- Types ---

type ViewMode = "scientific" | "modern";
type ColorType = "Success" | "Warning" | "Danger";

interface ChartPoint {
  date: string;
  displayDate: string;
  avg: number;
  min: number;
  max: number;
  errorUp: number;
  errorDown: number;
  colorType: ColorType;
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

function toDisplayPts(points: DailyGlucosePoint[], unit: GlucoseUnit, thresholds: { veryLow: number; low: number; high: number; veryHigh: number }): ChartPoint[] {
  const vl = convertGlucose(thresholds.veryLow, unit);
  const l = convertGlucose(thresholds.low, unit);
  const h = convertGlucose(thresholds.high, unit);
  const vh = convertGlucose(thresholds.veryHigh, unit);

  return points.map((p) => {
    const avg = convertGlucose(p.average, unit);
    const min = convertGlucose(p.min, unit);
    const max = convertGlucose(p.max, unit);
    
    let colorType: ColorType = "Success";
    if (avg < vl || avg > vh) colorType = "Danger";
    else if (avg < l || avg > h) colorType = "Warning";

    const errorUp = Math.max(0, max - avg);
    const errorDown = Math.max(0, avg - min);

    return {
      date: p.date,
      displayDate: formatDate(p.date),
      avg,
      min,
      max,
      errorUp,
      errorDown,
      colorType,
      avgSuccess: colorType === "Success" ? avg : NaN,
      errorUpSuccess: colorType === "Success" ? errorUp : NaN,
      errorDownSuccess: colorType === "Success" ? errorDown : NaN,
      avgWarning: colorType === "Warning" ? avg : NaN,
      errorUpWarning: colorType === "Warning" ? errorUp : NaN,
      errorDownWarning: colorType === "Warning" ? errorDown : NaN,
      avgDanger: colorType === "Danger" ? avg : NaN,
      errorUpDanger: colorType === "Danger" ? errorUp : NaN,
      errorDownDanger: colorType === "Danger" ? errorDown : NaN,
    };
  });
}

// --- Custom dot shapes ---

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function ScientificDot(props: any) {
  const { cx, cy, color } = props;
  if (cx == null || cy == null || Number.isNaN(Number(cx)) || Number.isNaN(Number(cy))) return null;
  return (
    <circle cx={cx} cy={cy} r={4} fill={color || "#27ae60"} stroke="var(--card-bg)" strokeWidth={1.5} />
  );
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function ModernDot(props: any) {
  const { cx, cy, color } = props;
  if (cx == null || cy == null || Number.isNaN(Number(cx)) || Number.isNaN(Number(cy))) return null;
  return (
    <circle cx={cx} cy={cy} r={6} fill={color || "#27ae60"} stroke="var(--card-bg)" strokeWidth={2} />
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
  const [mode, setMode] = useState<ViewMode>("scientific");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const raf = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(raf);
  }, []);

  const chartData = toDisplayPts(points, unit, thresholds);

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

  const isEmpty = chartData.length === 0;

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div>
          <h3 className={styles.title}>Daily Glucose Averages</h3>
          <p className={styles.subtitle}>Average, min and max with errors per day</p>
        </div>

        <div className={styles.switcher}>

          <button
            className={styles.switchBtn + (mode === "scientific" ? " " + styles.switchBtnActive : "")}
            onClick={() => setMode("scientific")}
          >
            Scientific
          </button>
          <button
            className={styles.switchBtn + (mode === "modern" ? " " + styles.switchBtnActive : "")}
            onClick={() => setMode("modern")}
          >
            Modern
          </button>
        </div>
      </div>

      <div className={styles.chartArea}>
        {isEmpty ? (
          <div className={styles.empty}>No glucose data for this period.</div>
        ) : !mounted ? null : (
          <ResponsiveContainer width="100%" height="100%" minHeight={280} minWidth={0} debounce={50}>
            <ComposedChart data={chartData} margin={{ top: 8, right: 42, bottom: 8, left: 12 }}>
              <CartesianGrid stroke="var(--border)" strokeDasharray="4 4" strokeOpacity={0.4} />
              <XAxis
                dataKey="displayDate"
                tick={{ fontSize: 11, fill: "var(--text-secondary)" }}
                tickLine={false}
                axisLine={{ stroke: "var(--border)" }}
                interval="preserveStartEnd"
                allowDuplicatedCategory={false}
              />
              <YAxis
                domain={domain}
                tick={{ fontSize: 11, fill: "var(--text-secondary)" }}
                tickLine={false}
                axisLine={false}
                width={42}
                label={{
                  value: unit,
                  angle: -90,
                  position: "insideLeft",
                  fontSize: 12,
                  fill: "var(--text-secondary)",
                  dx: -8
                }}
              />

              <ReferenceArea
                y1={l}
                y2={h}
                fill="var(--success)"
                fillOpacity={0.08}
                stroke="none"
              />

              <ReferenceLine
                y={vl}
                stroke="var(--danger)"
                strokeDasharray="4 4"
                label={{ value: String(vl), position: "right", fontSize: 11, fill: "var(--danger)", dx: 6 }}
              />
              <ReferenceLine
                y={l}
                stroke="var(--warning)"
                strokeDasharray="4 4"
                label={{ value: String(l), position: "right", fontSize: 11, fill: "var(--warning)", dx: 6 }}
              />
              <ReferenceLine
                y={h}
                stroke="var(--warning)"
                strokeDasharray="4 4"
                label={{ value: String(h), position: "right", fontSize: 11, fill: "var(--warning)", dx: 6 }}
              />
              <ReferenceLine
                y={vh}
                stroke="var(--danger)"
                strokeDasharray="4 4"
                label={{ value: String(vh), position: "right", fontSize: 11, fill: "var(--danger)", dx: 6 }}
              />

              <Tooltip
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                content={(props: any) => <ScatterTooltip {...props} unit={unit} />}
                cursor={{ stroke: "var(--border)", strokeWidth: 1 }}
              />

              {mode === "scientific" ? (
                <>
                  <Scatter dataKey="avgSuccess" fill="var(--success)" shape={(props) => <ScientificDot {...props} color="var(--success)" />}>
                    <ErrorBar dataKey="errorUpSuccess" width={5} strokeWidth={1.5} stroke="var(--success)" direction="y" />
                    <ErrorBar dataKey="errorDownSuccess" width={5} strokeWidth={1.5} stroke="var(--success)" direction="y" />
                  </Scatter>
                  <Scatter dataKey="avgWarning" fill="var(--warning)" shape={(props) => <ScientificDot {...props} color="var(--warning)" />}>
                    <ErrorBar dataKey="errorUpWarning" width={5} strokeWidth={1.5} stroke="var(--warning)" direction="y" />
                    <ErrorBar dataKey="errorDownWarning" width={5} strokeWidth={1.5} stroke="var(--warning)" direction="y" />
                  </Scatter>
                  <Scatter dataKey="avgDanger" fill="var(--danger)" shape={(props) => <ScientificDot {...props} color="var(--danger)" />}>
                    <ErrorBar dataKey="errorUpDanger" width={5} strokeWidth={1.5} stroke="var(--danger)" direction="y" />
                    <ErrorBar dataKey="errorDownDanger" width={5} strokeWidth={1.5} stroke="var(--danger)" direction="y" />
                  </Scatter>
                </>
              ) : (
                <>
                  <Scatter dataKey="avgSuccess" fill="var(--success)" shape={(props) => <ModernDot {...props} color="var(--success)" />}>
                    <ErrorBar dataKey="errorUpSuccess" width={12} strokeWidth={10} stroke="var(--success)" strokeOpacity={0.22} direction="y" />
                    <ErrorBar dataKey="errorDownSuccess" width={12} strokeWidth={10} stroke="var(--success)" strokeOpacity={0.22} direction="y" />
                  </Scatter>
                  <Scatter dataKey="avgWarning" fill="var(--warning)" shape={(props) => <ModernDot {...props} color="var(--warning)" />}>
                    <ErrorBar dataKey="errorUpWarning" width={12} strokeWidth={10} stroke="var(--warning)" strokeOpacity={0.22} direction="y" />
                    <ErrorBar dataKey="errorDownWarning" width={12} strokeWidth={10} stroke="var(--warning)" strokeOpacity={0.22} direction="y" />
                  </Scatter>
                  <Scatter dataKey="avgDanger" fill="var(--danger)" shape={(props) => <ModernDot {...props} color="var(--danger)" />}>
                    <ErrorBar dataKey="errorUpDanger" width={12} strokeWidth={10} stroke="var(--danger)" strokeOpacity={0.22} direction="y" />
                    <ErrorBar dataKey="errorDownDanger" width={12} strokeWidth={10} stroke="var(--danger)" strokeOpacity={0.22} direction="y" />
                  </Scatter>
                </>
              )}
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className={styles.legend}>
        {mode === "scientific" ? (
          <>
            <svg width="10" height="10">
              <circle cx="5" cy="5" r="4" fill="var(--text-secondary)" />
            </svg>
            <span className={styles.legendText}>Daily average</span>
            <svg width="10" height="16">
              <line x1="5" y1="0" x2="5" y2="16" stroke="var(--text-secondary)" strokeWidth="1.5" />
              <line x1="2" y1="0" x2="8" y2="0" stroke="var(--text-secondary)" strokeWidth="1.5" />
              <line x1="2" y1="16" x2="8" y2="16" stroke="var(--text-secondary)" strokeWidth="1.5" />
            </svg>
            <span className={styles.legendText}>Min - Max range (whisker error bars)</span>
          </>
        ) : (
          <>
            <svg width="12" height="12">
              <circle cx="6" cy="6" r="6" fill="var(--text-secondary)" />
            </svg>
            <span className={styles.legendText}>Daily average</span>
            <svg width="12" height="16">
              <rect x="0" y="0" width="12" height="16" rx="6" fill="var(--text-secondary)" fillOpacity={0.22} />
            </svg>
            <span className={styles.legendText}>Min - Max range (capsule)</span>
          </>
        )}
      </div>
    </div>
  );
}

