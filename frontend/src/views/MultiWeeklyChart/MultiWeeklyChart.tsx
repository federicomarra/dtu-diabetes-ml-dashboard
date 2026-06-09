"use client";

import { useMemo } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import { startOfWeek, getISOWeek } from "date-fns";
import type { GlucoseReading } from "@/models/types";
import { useGlucoseUnit } from "@/controllers/GlucoseUnitContext";
import { useGlucoseRanges } from "@/controllers/GlucoseRangesContext";
import { convertGlucose } from "@/models/glucoseUnits";
import {
  LOW_THRESHOLD,
  HIGH_THRESHOLD,
  VERY_HIGH_THRESHOLD,
  CHART_DOMAIN_MIN,
  CHART_DOMAIN_MAX,
} from "@/models/glucoseConfig";
import type { CustomThresholds } from "@/views/TIRChart/TIRChart";
import styles from "./MultiWeeklyChart.module.css";

// ─── Types ──────────────────────────────────────────────────

interface MultiWeeklyChartProps {
  readings?: GlucoseReading[];
}

interface DayData {
  date: Date;
  dayLabel: string;   // e.g. "Mon"
  dateNum: number;    // day-of-month number
  points: { minuteOfDay: number; glucose: number; status: string }[];
}

interface WeekGroup {
  weekKey: string;         // "W23 2025"
  weekNum: number;         // ISO week number
  startDate: Date;         // Monday of that week
  endDate: Date;           // Sunday
  days: DayData[];         // always 7 days, Mon → Sun
}

// ─── Constants ──────────────────────────────────────────────

const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

// ─── Helpers ────────────────────────────────────────────────

/** Returns the Monday of the ISO week containing `date`. */
function isoWeekMonday(date: Date): Date {
  return startOfWeek(date, { weekStartsOn: 1 });
}

/** Formats a Date as "DD/MM" locale-independently. */
function fmtDayMonth(d: Date): string {
  return `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}`;
}

/** Returns minutes since midnight for a given date. */
function minuteOfDay(d: Date): number {
  return d.getHours() * 60 + d.getMinutes();
}

// ─── Data grouping ──────────────────────────────────────────

function groupByWeek(
  readings: GlucoseReading[] | undefined,
  unit: "mmol/L" | "mg/dL"
): WeekGroup[] {
  if (!readings || readings.length === 0) return [];

  // Sort readings ascending
  const sorted = [...readings].sort(
    (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
  );

  // Map each reading to the Monday of its ISO week
  const weekMap = new Map<string, { monday: Date; readings: GlucoseReading[] }>();

  for (const r of sorted) {
    const d = new Date(r.timestamp);
    const monday = isoWeekMonday(d);
    const key = monday.toISOString().slice(0, 10); // "YYYY-MM-DD"
    if (!weekMap.has(key)) {
      weekMap.set(key, { monday, readings: [] });
    }
    weekMap.get(key)!.readings.push(r);
  }

  // Sort week keys ascending
  const sortedWeekKeys = [...weekMap.keys()].sort();

  return sortedWeekKeys.map((weekKey) => {
    const { monday, readings: weekReadings } = weekMap.get(weekKey)!;

    // Build 7 DayData entries (Mon=0 … Sun=6)
    const days: DayData[] = DAY_NAMES.map((dayLabel, i) => {
      const dayDate = new Date(monday);
      dayDate.setDate(monday.getDate() + i);
      const dateStr = dayDate.toISOString().slice(0, 10);

      const points = weekReadings
        .filter((r) => r.timestamp.slice(0, 10) === dateStr)
        .map((r) => ({
          minuteOfDay: minuteOfDay(new Date(r.timestamp)),
          glucose: convertGlucose(r.glucose_mmoll, unit),
          status: r.status,
        }))
        .sort((a, b) => a.minuteOfDay - b.minuteOfDay);

      return { date: dayDate, dayLabel, dateNum: dayDate.getDate(), points };
    });

    const sunday = new Date(monday);
    sunday.setDate(monday.getDate() + 6);

    const weekNum = getISOWeek(monday);

    return {
      weekKey,
      weekNum,
      startDate: monday,
      endDate: sunday,
      days,
    };
  });
}

// ─── Single day mini-chart ───────────────────────────────────

interface DayPanelProps {
  day: DayData;
  low: number;
  high: number;
  veryHigh: number;
  domainMin: number;
  domainMax: number;
  unit: string;
  isToday: boolean;
}

function DayPanel({ day, low, high, veryHigh, domainMin, domainMax, unit, isToday }: DayPanelProps) {
  const hasData = day.points.length > 0;

  // Recharts needs a 'key' field — use minuteOfDay
  const chartData = day.points.map((p) => ({
    t: p.minuteOfDay,
    g: p.glucose,
  }));

  // Color each data point based on glucose level
  const lineColor = hasData
    ? (() => {
        const lastGlucose = day.points[day.points.length - 1]?.glucose ?? 0;
        if (lastGlucose > veryHigh) return "var(--danger)";
        if (lastGlucose > high) return "var(--warning)";
        if (lastGlucose < low) return "var(--warning)";
        return "var(--primary)";
      })()
    : "var(--primary)";

  const formattedDate = `${String(day.date.getDate()).padStart(2, "0")}/${String(day.date.getMonth() + 1).padStart(2, "0")}`;

  return (
    <div className={`${styles.dayPanel} ${isToday ? styles.dayPanelToday : ""} ${!hasData ? styles.dayPanelEmpty : ""}`}>
      {/* Day header */}
      <div className={styles.dayHeader}>
        <span className={styles.dayName}>{day.dayLabel}</span>
        <span className={styles.dayDate}>{formattedDate}</span>
      </div>

      {/* Mini chart */}
      <div className={styles.dayChart}>
        {hasData ? (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={chartData}
              margin={{ top: 2, right: 2, bottom: 2, left: 2 }}
            >
              {/* Target range shading */}
              <ReferenceArea
                y1={low}
                y2={high}
                fill="var(--success)"
                fillOpacity={0.12}
              />
              {/* High threshold */}
              <ReferenceLine
                y={high}
                stroke="var(--warning)"
                strokeDasharray="3 3"
                strokeOpacity={0.7}
                strokeWidth={1}
              />
              {/* Very high threshold */}
              <ReferenceLine
                y={veryHigh}
                stroke="var(--danger)"
                strokeDasharray="3 3"
                strokeOpacity={0.7}
                strokeWidth={1}
              />
              {/* Low threshold */}
              <ReferenceLine
                y={low}
                stroke="var(--warning)"
                strokeDasharray="3 3"
                strokeOpacity={0.7}
                strokeWidth={1}
              />

              <XAxis dataKey="t" hide />
              <YAxis
                domain={[domainMin, domainMax]}
                hide
              />

              <Tooltip
                contentStyle={{
                  background: "var(--card-bg)",
                  border: "1px solid var(--border)",
                  borderRadius: "6px",
                  fontSize: "11px",
                  padding: "4px 8px",
                }}
                formatter={(value: unknown) => [`${value} ${unit}`, "Glucose"]}
                labelFormatter={(label: unknown) => {
                  const mins = Number(label);
                  const h = Math.floor(mins / 60);
                  const m = mins % 60;
                  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
                }}
              />

              <Line
                type="monotone"
                dataKey="g"
                stroke={lineColor}
                strokeWidth={1.5}
                dot={false}
                activeDot={{ r: 3, fill: lineColor }}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div className={styles.noData}>—</div>
        )}
      </div>
    </div>
  );
}

// ─── Week row ────────────────────────────────────────────────

interface WeekRowProps {
  week: WeekGroup;
  low: number;
  high: number;
  veryHigh: number;
  domainMin: number;
  domainMax: number;
  unit: string;
  todayStr: string;
}

function WeekRow({ week, low, high, veryHigh, domainMin, domainMax, unit, todayStr }: WeekRowProps) {
  const mondayLabel = fmtDayMonth(week.startDate);
  const sundayLabel = fmtDayMonth(week.endDate);

  return (
    <div className={styles.weekRow}>
      {/* Week label sidebar */}
      <div className={styles.weekLabel}>
        <span className={styles.weekNum}>W{week.weekNum}</span>
        <span className={styles.weekRange}>{mondayLabel}</span>
        <span className={styles.weekRangeSep}>–</span>
        <span className={styles.weekRange}>{sundayLabel}</span>
      </div>

      {/* 7 day panels */}
      <div className={styles.weekDays}>
        {week.days.map((day) => {
          const dayStr = day.date.toISOString().slice(0, 10);
          const isToday = dayStr === todayStr;
          return (
            <DayPanel
              key={dayStr}
              day={day}
              low={low}
              high={high}
              veryHigh={veryHigh}
              domainMin={domainMin}
              domainMax={domainMax}
              unit={unit}
              isToday={isToday}
            />
          );
        })}
      </div>
    </div>
  );
}

// ─── Main component ──────────────────────────────────────────

export default function MultiWeeklyChart({
  readings,
}: MultiWeeklyChartProps) {
  const { unit } = useGlucoseUnit();
  const { ranges: thresholds } = useGlucoseRanges();

  const low      = convertGlucose(thresholds?.low      ?? LOW_THRESHOLD,       unit);
  const high     = convertGlucose(thresholds?.high     ?? HIGH_THRESHOLD,      unit);
  const veryHigh = convertGlucose(thresholds?.veryHigh ?? VERY_HIGH_THRESHOLD, unit);
  const domainMin = convertGlucose(CHART_DOMAIN_MIN, unit);
  const domainMax = convertGlucose(CHART_DOMAIN_MAX, unit);

  const weeks = useMemo(
    () => groupByWeek(readings, unit),
    [readings, unit]
  );

  const todayStr = new Date().toISOString().slice(0, 10);

  if (weeks.length === 0) {
    return (
      <div className={styles.container}>
        <div className={styles.header}>
          <h3 className={styles.title}>Multi-Weekly Glucose Overview</h3>
        </div>
        <div className={styles.empty}>No glucose data available.</div>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <h3 className={styles.title}>Multi-Weekly Glucose Overview</h3>
        <div className={styles.legend}>
          <span className={styles.legendItem}>
            <span className={styles.legendDot} style={{ background: "var(--success)" }} />
            In Range ({low}–{high} {unit})
          </span>
          <span className={styles.legendItem}>
            <span className={styles.legendDot} style={{ background: "var(--warning)" }} />
            High / Low
          </span>
          <span className={styles.legendItem}>
            <span className={styles.legendDot} style={{ background: "var(--danger)" }} />
            Very High (&gt;{veryHigh} {unit})
          </span>
        </div>
      </div>

      {/* Day-of-week header row */}
      <div className={styles.dayHeaderRow}>
        <div className={styles.weekLabelSpacer} />
        <div className={styles.dayHeaderCells}>
          {DAY_NAMES.map((d) => (
            <div key={d} className={styles.dayHeaderCell}>{d}</div>
          ))}
        </div>
      </div>

      {/* Week rows */}
      <div className={styles.weeksContainer}>
        {weeks.map((week) => (
          <WeekRow
            key={week.weekKey}
            week={week}
            low={low}
            high={high}
            veryHigh={veryHigh}
            domainMin={domainMin}
            domainMax={domainMax}
            unit={unit}
            todayStr={todayStr}
          />
        ))}
      </div>

      {/* Y-axis scale legend */}
      <div className={styles.scaleHint}>
        <span>{domainMax} {unit}</span>
        <span className={styles.scaleBar} />
        <span>{low}–{high} {unit} target</span>
        <span className={styles.scaleBar} />
        <span>{domainMin} {unit}</span>
      </div>
    </div>
  );
}
