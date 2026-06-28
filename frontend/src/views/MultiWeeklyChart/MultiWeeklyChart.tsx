"use client";

import { useMemo, useState, useEffect } from "react";
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
  /*VERY_HIGH_THRESHOLD,*/
  CHART_DOMAIN_MIN,
  CHART_DOMAIN_MAX,
} from "@/models/glucoseConfig";
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

/** Returns "YYYY-MM-DD" in local timezone. */
function getLocalDateStr(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
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
    const key = getLocalDateStr(monday); // "YYYY-MM-DD" in local time
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
      const dateStr = getLocalDateStr(dayDate);

      const points = weekReadings
        .filter((r) => getLocalDateStr(new Date(r.timestamp)) === dateStr)
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
  /*veryHigh: number;*/
  domainMin: number;
  domainMax: number;
  unit: string;
  isToday: boolean;
  mounted: boolean;
}

function DayPanel({ day, low, high, /*veryHigh,*/ domainMin, domainMax, unit, isToday, mounted }: DayPanelProps) {
  const hasData = day.points.length > 0;

  // Recharts needs a 'key' field — use minuteOfDay
  const chartData = day.points.map((p) => ({
    t: p.minuteOfDay,
    g: p.glucose,
  }));

  // Color each data point based on glucose level
  const lineColor = hasData
    ? (() => {
        const meanDailyGlucose = day.points.map((p) => p.glucose).reduce((a, b) => a + b, 0) / day.points.length;
        /*if (meanDailyGlucose > veryHigh) return "var(--danger)";
        if (meanDailyGlucose < low) return "var(--warning)";*/
        if (meanDailyGlucose < low) return "var(--danger)";
        if (meanDailyGlucose > high) return "var(--warning)";

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
        {hasData && mounted ? (
          <ResponsiveContainer width="100%" height="100%" minHeight={0} minWidth={0}>
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
              {/*<ReferenceLine
                y={veryHigh}
                stroke="var(--danger)"
                strokeDasharray="3 3"
                strokeOpacity={0.7}
                strokeWidth={1}
              />*/}
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
  /*veryHigh: number;*/
  domainMin: number;
  domainMax: number;
  unit: string;
  todayStr: string;
  mounted: boolean;
}

function WeekRow({ week, low, high, /*veryHigh,*/ domainMin, domainMax, unit, todayStr, mounted }: WeekRowProps) {
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
          const dayStr = getLocalDateStr(day.date);
          const isToday = dayStr === todayStr;
          return (
            <DayPanel
              key={dayStr}
              day={day}
              low={low}
              high={high}
              /*veryHigh={veryHigh}*/
              domainMin={domainMin}
              domainMax={domainMax}
              unit={unit}
              isToday={isToday}
              mounted={mounted}
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
  /*const veryHigh = convertGlucose(thresholds?.veryHigh ?? VERY_HIGH_THRESHOLD, unit);*/
  const domainMin = convertGlucose(CHART_DOMAIN_MIN, unit);
  const domainMax = convertGlucose(CHART_DOMAIN_MAX, unit);

  const weeks = useMemo(
    () => groupByWeek(readings, unit),
    [readings, unit]
  );

  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    const raf = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(raf);
  }, []);

  const todayStr = getLocalDateStr(new Date());

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
            High (&gt;{high} {unit})
          </span>
          <span className={styles.legendItem}>
            <span className={styles.legendDot} style={{ background: "var(--danger)" }} />
            Low (&lt;{low} {unit})
          </span>
        </div>
      </div>

      <div className={styles.mainBody}>
        <div className={styles.gridArea}>
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
                /*veryHigh={veryHigh}*/
                domainMin={domainMin}
                domainMax={domainMax}
                unit={unit}
                todayStr={todayStr}
                mounted={mounted}
              />
            ))}
          </div>
        </div>

        {/* Approximate Y-axis legend on the right */}
        <div className={styles.verticalScaleHint}>
           <div className={styles.verticalScaleLabel}>{domainMax}</div>
           <div className={styles.verticalScaleBar} />
           
           {/*weeks.length > 2 && (
             <>
               <div className={styles.verticalScaleLabel} style={{ color: "var(--danger)" }}>{veryHigh}</div>
               <div className={styles.verticalScaleBar} />
             </>
           )}*/}

           {weeks.length > 1 && (
             <>
               <div className={styles.verticalScaleTarget}>
                  <div style={{ color: "var(--warning)" }}>{high}</div>
                  <div className={styles.verticalScaleTargetText}>Target</div>
                  <div style={{ color: "var(--danger)" }}>{low}</div>
               </div>
               <div className={styles.verticalScaleBar} />
             </>
           )}

           <div className={styles.verticalScaleLabel}>{domainMin}</div>
           <div className={styles.verticalScaleUnit}>{unit}</div>
        </div>
      </div>
    </div>
  );
}
