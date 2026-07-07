"use client";

import { useState, useEffect, useCallback, useRef } from "react";
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
import {
  format,
  subDays,
  startOfDay,
  endOfDay,
  differenceInDays,
  startOfMonth,
  endOfMonth,
  eachDayOfInterval,
  getDay,
  addMonths,
  subMonths,
  isSameDay,
  isAfter,
} from "date-fns";
import type { GlucoseReading, AnomalyDetection } from "@/models/types";
import { getGlucoseReadings, getAnomalies } from "@/models/api";
import { useGlucoseUnit } from "@/controllers/GlucoseUnitContext";
import { useGlucoseRanges } from "@/controllers/GlucoseRangesContext";
import { useSeverityInference } from "@/controllers/SeverityInferenceContext";
import { convertGlucose } from "@/models/glucoseUnits";
import {
  LOW_THRESHOLD,
  HIGH_THRESHOLD,
  VERY_HIGH_THRESHOLD,
  CHART_DOMAIN_MIN,
  CHART_DOMAIN_MAX,
  VERY_LOW_THRESHOLD,
} from "@/models/glucoseConfig";
import styles from "./GlucoseDailyChart.module.css";

const TYPE_LABELS: Record<string, string> = {
  missed_bolus: "Missed Bolus",
  late_bolus: "Late Bolus",
  unusual_pattern: "Unusual Pattern",
};

interface CustomDotProps {
  cx?: number;
  cy?: number;
  payload?: {
    anomalies?: AnomalyDetection[];
  };
}

const CustomDot = (props: CustomDotProps) => {
  const { cx, cy, payload } = props;
  if (!cx || !cy || !payload || !payload.anomalies || payload.anomalies.length === 0) return null;

  const anomaliesList = payload.anomalies;
  const isMissedBolus = anomaliesList.some((a) => a.anomaly_type === "missed_bolus");
  const color = isMissedBolus ? "var(--danger)" : "var(--warning)";

  return (
    <g key={`dot-${cx}-${cy}`}>
      {/* Outer Halo ring (radius 3px, 30% opacity) */}
      <circle
        cx={cx}
        cy={cy}
        r={3}
        fill={color}
        fillOpacity={0.3}
        stroke="none"
      />
      {/* Inner Solid dot (radius 1.5px) */}
      <circle
        cx={cx}
        cy={cy}
        r={1.5}
        fill={color}
      />
    </g>
  );
};

interface GlucoseDailyChartProps {
  /** Pass to enable self-fetching day-by-day navigation. */
  patientId?: number;
  /** Fallback readings when patientId is not provided (e.g. demo/patient page). */
  readings?: GlucoseReading[];
  /** Anomalies for the patient. */
  anomalies?: AnomalyDetection[];
  title?: string;
  /** Called whenever the day offset changes (0 = latest, 1 = 1 day ago, …). */
  onOffsetChange?: (offset: number, latestDay: Date | null) => void;
  /** Called once the latest anchor day is resolved from the API. */
  onLatestDayResolved?: (day: Date) => void;
}

export default function GlucoseDailyChart({
  patientId,
  readings: fallbackReadings,
  anomalies,
  title,
  onOffsetChange,
  onLatestDayResolved,
}: GlucoseDailyChartProps) {
  const { unit } = useGlucoseUnit();
  const { ranges: thresholds } = useGlucoseRanges();
  const { minSeverity } = useSeverityInference();

  // The midnight Date of the latest available day (anchor from ?last=1d response).
  // All backward navigation is relative to this anchor.
  const [latestDay, setLatestDay] = useState<Date | null>(null);

  // offset: 0 = latest available day, 1 = one day before, etc.
  const [offset, setOffset] = useState(0);

  // Direction of the last navigation action (drives wipe + line animation)
  // 'right' = forward in time (overlay wipes right, line draws left→right)
  // 'left'  = back in time   (overlay wipes left,  line draws right→left)
  const [slideDirection, setSlideDirection] = useState<'left' | 'right'>('right');
  // Bumped on every navigation so <Line key> changes → Recharts replays its draw animation
  const animationKey = useRef(0);
  // True while the wipe overlay is visible
  const [isAnimating, setIsAnimating] = useState(false);

  const [fetchedReadings, setFetchedReadings] = useState<GlucoseReading[] | null>(null);
  const [fetchedAnomalies, setFetchedAnomalies] = useState<AnomalyDetection[] | null>(null);
  const [loading, setLoading] = useState(false);

  const [showCalendar, setShowCalendar] = useState(false);
  const [calendarMonth, setCalendarMonth] = useState<Date>(new Date());
  const calendarRef = useRef<HTMLDivElement>(null);

  // Initialize calendarMonth when latestDay is fetched
  useEffect(() => {
    if (latestDay) {
      setCalendarMonth(latestDay);
    }
  }, [latestDay]);

  // Click outside to close calendar
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (calendarRef.current && !calendarRef.current.contains(event.target as Node)) {
        setShowCalendar(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

  /** Fetch the window [startOfDay(anchor - offsetDays), endOfDay(anchor - offsetDays)]. */
  const fetchByAnchor = useCallback(
    async (anchor: Date, offsetDays: number) => {
      if (!patientId) return;
      setLoading(true);
      try {
        const base = subDays(anchor, offsetDays);
        const startIso = startOfDay(base).toISOString();
        const endIso = endOfDay(base).toISOString();
        const [readingsResp, anomaliesResp] = await Promise.all([
          getGlucoseReadings(patientId, {
            start: startIso,
            end: endIso,
          }),
          getAnomalies(patientId, {
            start: startIso,
            end: endIso,
          })
        ]);
        setFetchedReadings(readingsResp.readings);
        setFetchedAnomalies(anomaliesResp.anomalies);
      } catch {
        setFetchedReadings([]);
        setFetchedAnomalies([]);
      } finally {
        setLoading(false);
      }
    },
    [patientId]
  );

  /** On mount (or patientId change): fetch latest day via ?last=1d to discover the anchor date. */
  useEffect(() => {
    if (!patientId) return;
    let cancelled = false;
    setLoading(true);
    getGlucoseReadings(patientId, { last: "1d" })
      .then((resp) => {
        if (cancelled) return;
        setFetchedReadings(resp.readings);
        if (resp.readings.length > 0) {
          // Use the latest reading timestamp as the anchor date
          const latest = resp.readings.reduce((a, b) =>
            new Date(a.timestamp) > new Date(b.timestamp) ? a : b
          );
          const day = startOfDay(new Date(latest.timestamp));
          setLatestDay(day);
          onLatestDayResolved?.(day);
          onOffsetChange?.(0, day);

          // Fetch anomalies for this resolved day
          const startIso = startOfDay(day).toISOString();
          const endIso = endOfDay(day).toISOString();
          getAnomalies(patientId, { start: startIso, end: endIso })
            .then((anomResp) => {
              if (!cancelled) {
                setFetchedAnomalies(anomResp.anomalies);
              }
            })
            .catch(() => {
              if (!cancelled) setFetchedAnomalies([]);
            });
        }
      })
      .catch(() => {
        if (!cancelled) {
          setFetchedReadings([]);
          setFetchedAnomalies([]);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [patientId]); // eslint-disable-line react-hooks/exhaustive-deps

  const triggerAnimation = (dir: 'left' | 'right') => {
    setSlideDirection(dir);
    animationKey.current += 1;
    setIsAnimating(true);
    // Remove overlay after the CSS animation completes
    setTimeout(() => setIsAnimating(false), 360);
  };

  const handlePrev = () => {
    if (!latestDay) return;
    const next = offset + 1;
    triggerAnimation('left');
    setOffset(next);
    fetchByAnchor(latestDay, next);
    onOffsetChange?.(next, latestDay);
  };

  const handleNext = () => {
    if (!latestDay || offset === 0) return;
    const next = offset - 1;
    triggerAnimation('right');
    setOffset(next);
    fetchByAnchor(latestDay, next);
    onOffsetChange?.(next, latestDay);
  };

  const handleGoLatest = () => {
    if (!latestDay || offset === 0) return;
    triggerAnimation('right');
    setOffset(0);
    fetchByAnchor(latestDay, 0);
    onOffsetChange?.(0, latestDay);
  };

  const activeDate = latestDay ? subDays(latestDay, offset) : new Date();

  const handleCalendarDayClick = (day: Date) => {
    if (!latestDay) return;
    const selected = startOfDay(day);
    if (isAfter(selected, latestDay)) return;

    const diff = differenceInDays(latestDay, selected);
    if (diff < 0) return;

    const direction = diff > offset ? 'left' : 'right';
    triggerAnimation(direction);
    setOffset(diff);
    fetchByAnchor(latestDay, diff);
    onOffsetChange?.(diff, latestDay);
    setShowCalendar(false);
  };

  // Calendar variables
  const monthStart = startOfMonth(calendarMonth);
  const monthEnd = endOfMonth(calendarMonth);
  const startDayOfWeek = getDay(monthStart);
  const daysInMonth = eachDayOfInterval({ start: monthStart, end: monthEnd });

  // Decide which readings to display
  const activeReadings = patientId ? (fetchedReadings ?? []) : (fallbackReadings ?? []);

  // Filter anomalies for the active day and passes severity filter
  const rawAnomalies = patientId ? (fetchedAnomalies ?? anomalies ?? []) : (anomalies ?? []);
  const activeAnomalies = rawAnomalies.filter((a) => {
    if (!a.detected_at) return false;
    const isSame = isSameDay(new Date(a.detected_at), activeDate);
    const passesSeverity = a.severity == null || a.severity >= minSeverity;
    return isSame && passesSeverity;
  });

  const chartData = activeReadings
    .slice()
    .map((r) => {
      const d = new Date(r.timestamp);
      // Find anomalies associated with this reading (either by glucose_reading_id or proximity within 15 mins)
      const matchingAnomalies = activeAnomalies.filter((a) => {
        if (a.glucose_reading_id === r.id) return true;
        if (a.detected_at) {
          const diffMs = Math.abs(new Date(a.detected_at).getTime() - d.getTime());
          return diffMs < 15 * 60 * 1000;
        }
        return false;
      });

      return {
        id: r.id,
        // Fractional hour: 08:30 → 8.5, used as the numeric X value
        hour: d.getHours() + d.getMinutes() / 60,
        time: format(d, "HH:mm"),
        fullTime: format(d, "MMM d, HH:mm"),
        glucose: convertGlucose(r.glucose_mmoll, unit),
        status: r.status,
        anomalies: matchingAnomalies,
      };
    })
    .sort((a, b) => a.hour - b.hour);

  const veryLow  = convertGlucose(thresholds?.veryLow  ?? VERY_LOW_THRESHOLD,  unit);
  const low      = convertGlucose(thresholds?.low      ?? LOW_THRESHOLD,       unit);
  const high     = convertGlucose(thresholds?.high     ?? HIGH_THRESHOLD,      unit);
  const veryHigh = convertGlucose(thresholds?.veryHigh ?? VERY_HIGH_THRESHOLD, unit);
  const domainMin = convertGlucose(CHART_DOMAIN_MIN, unit);
  const domainMax = convertGlucose(CHART_DOMAIN_MAX, unit);

  // Display label: derived from the first reading timestamp, or from the expected anchor date
  const displayDate = (() => {
    const reading = activeReadings[0];
    if (reading) return format(new Date(reading.timestamp), "EEE, MMM d yyyy");
    if (latestDay) return format(subDays(latestDay, offset), "EEE, MMM d yyyy");
    return "—";
  })();

  const isLatest = offset === 0;
  const chartTitle = title || "Glucose daily trace";

  return (
    <div className={styles.container}>
      {/* Header: title + day navigation */}
      <div className={styles.header}>
        <h3 className={styles.title}>{chartTitle}</h3>

        {patientId && (
          <div className={styles.dayNav}>
            {/* "Back to latest" badge — only when browsing past days */}
            {!isLatest && (
              <button
                id="glucose-chart-go-latest"
                className={styles.latestBtn}
                onClick={handleGoLatest}
                title="Jump to latest available day"
              >
                Latest ›
              </button>
            )}

            {/* ‹ go further back */}
            <button
              id="glucose-chart-prev-day"
              className={styles.navBtn}
              onClick={handlePrev}
              disabled={!latestDay}
              title="Previous day"
              aria-label="Previous day"
            >
              ‹
            </button>

            <div className={styles.dateContainer} ref={calendarRef}>
              <button
                type="button"
                className={styles.dayLabel}
                onClick={() => {
                  setShowCalendar(!showCalendar);
                  if (activeDate) {
                    setCalendarMonth(activeDate);
                  }
                }}
                title="Click to open calendar"
              >
                {displayDate} <span style={{ marginLeft: "0.4rem", fontSize: "0.85rem" }}></span>
              </button>

              {showCalendar && (
                <div className={styles.calendarPopup}>
                  <div className={styles.calendarHeader}>
                    <button
                      type="button"
                      onClick={() => setCalendarMonth(subMonths(calendarMonth, 1))}
                      className={styles.calendarNavBtn}
                      title="Previous month"
                    >
                      &lt;
                    </button>
                    <span className={styles.calendarMonthName}>
                      {format(calendarMonth, "MMMM yyyy")}
                    </span>
                    <button
                      type="button"
                      onClick={() => setCalendarMonth(addMonths(calendarMonth, 1))}
                      className={styles.calendarNavBtn}
                      title="Next month"
                    >
                      &gt;
                    </button>
                  </div>

                  <div className={styles.calendarWeekdays}>
                    {["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"].map((wd) => (
                      <span key={wd} className={styles.calendarWeekday}>
                        {wd}
                      </span>
                    ))}
                  </div>

                  <div className={styles.calendarGrid}>
                    {Array.from({ length: startDayOfWeek }).map((_, i) => (
                      <span key={`empty-${i}`} className={styles.calendarEmptyCell} />
                    ))}

                    {daysInMonth.map((day) => {
                      const isSelected = isSameDay(day, activeDate);
                      const isFuture = latestDay ? isAfter(startOfDay(day), latestDay) : false;
                      return (
                        <button
                          key={day.toISOString()}
                          type="button"
                          disabled={isFuture}
                          onClick={() => handleCalendarDayClick(day)}
                          className={`${styles.calendarDayBtn} ${
                            isSelected ? styles.calendarDaySelected : ""
                          } ${isFuture ? styles.calendarDayDisabled : ""}`}
                        >
                          {format(day, "d")}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>

            {/* › go forward toward latest */}
            <button
              id="glucose-chart-next-day"
              className={`${styles.navBtn} ${isLatest ? styles.navBtnDisabled : ""}`}
              onClick={handleNext}
              disabled={isLatest}
              title="Next day"
              aria-label="Next day"
            >
              ›
            </button>
          </div>
        )}
      </div>

      {/* Chart — axes are always stable; only the Line re-animates */}
      <div className={loading ? styles.chartLoading : undefined} style={{ position: 'relative' }}>
        <ResponsiveContainer width="100%" height={320}>
          <LineChart data={chartData} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />

            {/* Target range shading */}
            <ReferenceArea
              y1={low}
              y2={high}
              fill="var(--success)"
              fillOpacity={0.08}
              stroke="none"
            />

            {/* Clinical threshold lines */}
            <ReferenceLine
              y={veryLow}
              stroke="var(--danger)"
              strokeDasharray="4 4"
              label={{ value: String(veryLow), position: "left", fontSize: 11 }}
            />
            <ReferenceLine
              y={low}
              stroke="var(--warning)"
              strokeDasharray="4 4"
              label={{ value: String(low), position: "left", fontSize: 11 }}
            />
            
            <ReferenceLine
              y={high}
              stroke="var(--warning)"
              strokeDasharray="4 4"
              label={{ value: String(high), position: "left", fontSize: 11 }}
            />
            <ReferenceLine
              y={veryHigh}
              stroke="var(--danger)"
              strokeDasharray="4 4"
              label={{ value: String(veryHigh), position: "left", fontSize: 11 }}
            />

            <XAxis
              dataKey="hour"
              type="number"
              domain={[0, 24]}
              ticks={Array.from({ length: 24 }, (_, i) => i)}
              tickFormatter={(h: number) => String(h)}
              tick={{ fontSize: 10 }}
              interval={0}
              angle={-45}
              textAnchor="end"
              height={50}
            />
            <YAxis
              domain={[domainMin, domainMax]}
              tick={{ fontSize: 11 }}
              label={{
                value: unit,
                angle: -90,
                position: "insideLeft",
                fontSize: 12,
              }}
            />
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload || !payload.length) return null;
                const data = payload[0].payload as {
                  time?: string;
                  glucose?: number;
                  anomalies?: AnomalyDetection[];
                };
                const anomaliesList = data.anomalies || [];
                return (
                  <div className={styles.customTooltip}>
                    <div className={styles.tooltipTime}>{data.time}</div>
                    <div className={styles.tooltipValue}>
                      <span className={styles.tooltipLabel}>Glucose:</span>
                      <span className={styles.tooltipGlucose}>{data.glucose} {unit}</span>
                    </div>
                    {anomaliesList.length > 0 && (
                      <div className={styles.tooltipAnomalies}>
                        {anomaliesList.map((anom) => {
                          const isSevere = anom.severity != null && anom.severity >= 4;
                          const accentColor = isSevere ? "var(--danger)" : "var(--warning)";
                          return (
                            <div
                              key={anom.id}
                              className={styles.tooltipAnomalyItem}
                              style={{
                                background: `color-mix(in srgb, ${accentColor} 8%, transparent)`,
                                borderLeft: `3px solid ${accentColor}`,
                              }}
                            >
                              <span className={styles.tooltipAnomalyType}>
                                ⚠️ {TYPE_LABELS[anom.anomaly_type] || anom.anomaly_type}
                                {anom.severity != null && ` (${anom.severity.toFixed(1)}σ)`}
                              </span>
                              {anom.description && (
                                <div className={styles.tooltipAnomalyDesc}>{anom.description}</div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              }}
            />

            {/* key change forces re-render on day navigation; wipe overlay handles the visual transition */}
            <Line
              key={animationKey.current}
              type="monotone"
              dataKey="glucose"
              stroke="var(--primary)"
              strokeWidth={2}
              dot={<CustomDot />}
              activeDot={{ r: 4, fill: "var(--primary)" }}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>

        {/* Directional wipe overlay — slides away to reveal the newly drawn line */}
        {isAnimating && (
          <div
            aria-hidden
            className={
              slideDirection === 'left' ? styles.wipeLeft : styles.wipeRight
            }
          />
        )}

        {chartData.length === 0 && !loading && (
          <p className={styles.noData}>No glucose data for this day.</p>
        )}
      </div>
    </div>
  );
}
