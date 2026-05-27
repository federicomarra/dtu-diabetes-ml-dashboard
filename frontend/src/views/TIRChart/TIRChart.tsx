"use client";

import { useState, useEffect, useRef, ReactNode } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ResponsiveContainer,
  Cell,
} from "recharts";
import type { TimeInRange } from "@/models/types";
import { useGlucoseUnit } from "@/controllers/GlucoseUnitContext";
import { convertGlucose, formatGlucose } from "@/models/glucoseUnits";
import type { GlucoseUnit } from "@/models/glucoseUnits";
import {
  VERY_LOW_THRESHOLD,
  LOW_THRESHOLD,
  HIGH_THRESHOLD,
  VERY_HIGH_THRESHOLD,
} from "@/models/glucoseConfig";
import styles from "./TIRChart.module.css";

// ─── Threshold types ────────────────────────────────────────

interface CustomThresholds {
  veryHigh: number; // mmol/L
  high: number;     // mmol/L
  low: number;      // mmol/L
  veryLow: number;  // mmol/L
}

const DEFAULT_THRESHOLDS: CustomThresholds = {
  veryHigh: VERY_HIGH_THRESHOLD,
  high: HIGH_THRESHOLD,
  low: LOW_THRESHOLD,
  veryLow: VERY_LOW_THRESHOLD,
};

/** Convert a mmol/L threshold for display in `unit`. */
function toDisplay(mmoll: number, unit: GlucoseUnit): string {
  return convertGlucose(mmoll, unit).toString();
}

/** Parse a display string back to mmol/L. */
function fromDisplay(value: string, unit: GlucoseUnit): number {
  const n = parseFloat(value);
  if (isNaN(n)) return NaN;
  if (unit === "mg/dL") return n / 18.0182;
  return n;
}

interface TIRChartProps {
  tir: TimeInRange;
}

const RANGE_COLORS = {
  very_high: "#e74c3c",
  high: "#f39c12",
  in_range: "#27ae60",
  low: "#e67e22",
  very_low: "#c0392b",
};

type ViewMode = "stacked" | "barchart";

/** Format a Date as DD/MM — locale-independent to avoid SSR hydration mismatches. */
function formatDayMonth(d: Date): string {
  return `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}`;
}

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
  const start_day: string = formatDayMonth(new Date(Date.now() - days * 24 * 60 * 60 * 1000));
  const end_day: string = formatDayMonth(new Date());
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
  thresholds: CustomThresholds;
}

function pctToMinutes(pct: number): string {
  const totalMinutes = Math.round((pct / 100) * 24 * 60);
  const h = Math.floor(totalMinutes / 60);
  const m = totalMinutes % 60;
  if (h === 0) return `${m}min.`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}min.`;
}

function StackedView({ tir, thresholds }: StackedViewProps) {
  const { unit } = useGlucoseUnit();

  const ranges = [
    {
      key: "very_high" as const,
      label: "Very High",
      pct: tir.very_high_pct,
      color: RANGE_COLORS.very_high,
      rangeLabel: `>${formatGlucose(thresholds.veryHigh, unit)}`,
    },
    {
      key: "high" as const,
      label: "High",
      pct: tir.high_pct,
      color: RANGE_COLORS.high,
      rangeLabel: `${formatGlucose(thresholds.high, unit)} – ${formatGlucose(thresholds.veryHigh, unit)}`,
    },
    {
      key: "in_range" as const,
      label: "In Range",
      pct: tir.in_range_pct,
      color: RANGE_COLORS.in_range,
      rangeLabel: `${formatGlucose(thresholds.low, unit)} – ${formatGlucose(thresholds.high, unit)}`,
    },
    {
      key: "low" as const,
      label: "Low",
      pct: tir.low_pct,
      color: RANGE_COLORS.low,
      rangeLabel: `${formatGlucose(thresholds.veryLow, unit)} – ${formatGlucose(thresholds.low, unit)}`,
    },
    {
      key: "very_low" as const,
      label: "Very Low",
      pct: tir.very_low_pct,
      color: RANGE_COLORS.very_low,
      rangeLabel: `<${formatGlucose(thresholds.veryLow, unit)}`,
    },
  ];

  // The threshold values displayed on the left axis (top → bottom order in CSS)
  const thresholdLabels = [
    { value: thresholds.veryHigh, after: "very_high" },
    { value: thresholds.high, after: "high" },
    { value: thresholds.low, after: "in_range" },
    { value: thresholds.veryLow, after: "low" },
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

interface BarChartViewProps {
  tir: TimeInRange;
  thresholds: CustomThresholds;
}

function BarChartView({ tir, thresholds }: BarChartViewProps) {
  const { unit } = useGlucoseUnit();

  const data = [
    {
      name: "Very High",
      pct: tir.very_high_pct,
      key: "very_high" as const,
      range: `>${formatGlucose(thresholds.veryHigh, unit)}`,
    },
    {
      name: "High",
      pct: tir.high_pct,
      key: "high" as const,
      range: `${formatGlucose(thresholds.high, unit)} – ${formatGlucose(thresholds.veryHigh, unit)}`,
    },
    {
      name: "In Range",
      pct: tir.in_range_pct,
      key: "in_range" as const,
      range: `${formatGlucose(thresholds.low, unit)} – ${formatGlucose(thresholds.high, unit)}`,
    },
    {
      name: "Low",
      pct: tir.low_pct,
      key: "low" as const,
      range: `${formatGlucose(thresholds.veryLow, unit)} – ${formatGlucose(thresholds.low, unit)}`,
    },
    {
      name: "Very Low",
      pct: tir.very_low_pct,
      key: "very_low" as const,
      range: `<${formatGlucose(thresholds.veryLow, unit)}`,
    },
  ];

  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} layout="vertical" margin={{ left: 0 }}>
        <CartesianGrid
          vertical={true}
          horizontal={false}
          stroke="var(--border)"
          strokeDasharray="4 4"
          strokeOpacity={30}
        />
        <XAxis type="number" domain={[0, 100]} unit="%" tick={{ fontSize: 11 }} />
        <YAxis
          type="category"
          dataKey="name"
          tick={{ fontSize: 11 }}
          width={80}
        />
        <Tooltip
          formatter={(value: unknown, _name: unknown, props: { payload?: { range?: string } }) => [
            `${value}%`,
            props.payload?.range ?? "Percentage",
          ]}
          contentStyle={{
            background: "var(--card-bg)",
            border: "1px solid var(--border)",
            borderRadius: "8px",
          }}
          labelStyle={{
            color: "var(--text-primary)",
          }}
          itemStyle={{
            color: "var(--text-secondary)",
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

// ─── Range Customization Modal ─────────────────────────────

interface RangesModalProps {
  unit: GlucoseUnit;
  thresholds: CustomThresholds;
  onApply: (t: CustomThresholds) => void;
  onClose: () => void;
}

function RangesModal({ unit, thresholds, onApply, onClose }: RangesModalProps) {
  const [draft, setDraft] = useState({
    veryHigh: toDisplay(thresholds.veryHigh, unit),
    high: toDisplay(thresholds.high, unit),
    low: toDisplay(thresholds.low, unit),
    veryLow: toDisplay(thresholds.veryLow, unit),
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const overlayRef = useRef<HTMLDivElement>(null);

  // Close on backdrop click
  const handleOverlayClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === overlayRef.current) onClose();
  };

  const validate = (): CustomThresholds | null => {
    const vh = fromDisplay(draft.veryHigh, unit);
    const h = fromDisplay(draft.high, unit);
    const l = fromDisplay(draft.low, unit);
    const vl = fromDisplay(draft.veryLow, unit);
    const errs: Record<string, string> = {};
    if (isNaN(vh)) errs.veryHigh = "Invalid number";
    if (isNaN(h)) errs.high = "Invalid number";
    if (isNaN(l)) errs.low = "Invalid number";
    if (isNaN(vl)) errs.veryLow = "Invalid number";
    // Ordering: vl < l < h < vh — check every adjacent and cross pair
    if (!errs.veryLow && !errs.low && vl >= l) errs.low = "Must be > Very Low";
    if (!errs.veryLow && !errs.high && vl >= h) errs.high = "Must be > Very Low";
    if (!errs.veryLow && !errs.veryHigh && vl >= vh) errs.veryHigh = "Must be > Very Low";
    if (!errs.low && !errs.high && l >= h) errs.high = "Must be > Low";
    if (!errs.low && !errs.veryHigh && l >= vh) errs.veryHigh = "Must be > Low";
    if (!errs.high && !errs.veryHigh && h >= vh) errs.veryHigh = "Must be > High";
    setErrors(errs);
    if (Object.keys(errs).length > 0) return null;
    return { veryLow: vl, low: l, high: h, veryHigh: vh };
  };

  const handleApply = () => {
    const t = validate();
    if (t) { onApply(t); onClose(); }
  };

  const handleReset = () => {
    setDraft({
      veryLow: toDisplay(DEFAULT_THRESHOLDS.veryLow, unit),
      low: toDisplay(DEFAULT_THRESHOLDS.low, unit),
      high: toDisplay(DEFAULT_THRESHOLDS.high, unit),
      veryHigh: toDisplay(DEFAULT_THRESHOLDS.veryHigh, unit),
    });
    setErrors({});
  };

  const fields: { key: keyof typeof draft; label: string; color: string }[] = [
    { key: "veryHigh", label: "Very High", color: RANGE_COLORS.very_high },
    { key: "high", label: "High", color: RANGE_COLORS.high },
    { key: "low", label: "Low", color: RANGE_COLORS.low },
    { key: "veryLow", label: "Very Low", color: RANGE_COLORS.very_low },
  ];

  return (
    <div className={styles.modalOverlay} ref={overlayRef} onClick={handleOverlayClick}>
      <div className={styles.modal}>
        <div className={styles.modalHeader}>
          <h4 className={styles.modalTitle}>Customize Ranges</h4>
          <button className={styles.modalClose} onClick={onClose} aria-label="Close">✕</button>
        </div>

        <p className={styles.modalSubtitle}>
          Thresholds in <strong>{unit}</strong>. Values apply to all views.
        </p>

        <div className={styles.modalFields}>
          {fields.map(({ key, label, color }) => (
            <div key={key} className={styles.fieldRow}>
              <label className={styles.fieldLabel}>
                <span className={styles.fieldSwatch} style={{ background: color }} />
                {label}
              </label>
              <div className={styles.fieldInputWrap}>
                <input
                  id={`tir-range-${key}`}
                  type="number"
                  step={unit === "mg/dL" ? 1 : 0.1}
                  className={`${styles.fieldInput} ${errors[key] ? styles.fieldInputError : ""}`}
                  value={draft[key]}
                  onChange={(e) => {
                    setDraft((d) => ({ ...d, [key]: e.target.value }));
                    setErrors((err) => { const next = { ...err }; delete next[key]; return next; });
                  }}
                />
                {errors[key] && <span className={styles.fieldError}>{errors[key]}</span>}
              </div>
            </div>
          ))}
        </div>

        <div className={styles.modalFooter}>
          <button className={styles.resetBtn} onClick={handleReset}>Reset to defaults</button>
          <div className={styles.footerActions}>
            <button className={styles.cancelBtn} onClick={onClose}>Cancel</button>
            <button className={styles.applyBtn} onClick={handleApply}>Apply</button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Main component ────────────────────────────────────────

export default function TIRChart({ tir }: TIRChartProps) {
  const [mode, setMode] = useState<ViewMode>("stacked");
  const [thresholds, setThresholds] = useState<CustomThresholds>(DEFAULT_THRESHOLDS);
  const [showRangesModal, setShowRangesModal] = useState(false);
  const { unit } = useGlucoseUnit();

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

        <div className={styles.headerRight}>
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

          {/* Ranges customization button */}
          <button
            id="tir-customize-ranges-btn"
            className={`${styles.rangesBtn} ${showRangesModal ? styles.rangesBtnActive : ""}`}
            onClick={() => setShowRangesModal((v) => !v)}
            title="Customize glucose ranges"
          >
            <svg width="13" height="13" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
              <path fillRule="evenodd" clipRule="evenodd" d="M11.49 3.17c-.38-1.56-2.6-1.56-2.98 0a1.532 1.532 0 01-2.286.948c-1.372-.836-2.942.734-2.106 2.106.54.886.061 2.042-.947 2.287-1.561.379-1.561 2.6 0 2.978a1.532 1.532 0 01.947 2.287c-.836 1.372.734 2.942 2.106 2.106a1.532 1.532 0 012.287.947c.379 1.561 2.6 1.561 2.978 0a1.533 1.533 0 012.287-.947c1.372.836 2.942-.734 2.106-2.106a1.533 1.533 0 01.947-2.287c1.561-.379 1.561-2.6 0-2.978a1.532 1.532 0 01-.947-2.287c.836-1.372-.734-2.942-2.106-2.106a1.532 1.532 0 01-2.287-.947zM10 13a3 3 0 100-6 3 3 0 000 6z" />
            </svg>
            Custom Ranges
          </button>
        </div>
      </div>

      {/* Chart — fixed-height wrapper keeps the card size stable on toggle */}
      <div className={styles.chartArea}>
        {mode === "stacked" ? (
          <StackedView tir={tir} thresholds={thresholds} />
        ) : (
          <BarChartView tir={tir} thresholds={thresholds} />
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

      {/* Ranges customization modal */}
      {showRangesModal && (
        <RangesModal
          unit={unit}
          thresholds={thresholds}
          onApply={setThresholds}
          onClose={() => setShowRangesModal(false)}
        />
      )}
    </div>
  );
}
