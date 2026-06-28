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
import { format, subDays, startOfDay, endOfDay } from "date-fns";
import type { GlucoseReading } from "@/models/types";
import { getGlucoseReadings } from "@/models/api";
import { useGlucoseUnit } from "@/controllers/GlucoseUnitContext";
import { useGlucoseRanges } from "@/controllers/GlucoseRangesContext";
import { convertGlucose } from "@/models/glucoseUnits";
import {
  LOW_THRESHOLD,
  HIGH_THRESHOLD,
  VERY_HIGH_THRESHOLD,
  CHART_DOMAIN_MIN,
  CHART_DOMAIN_MAX,
  VERY_LOW_THRESHOLD,
} from "@/models/glucoseConfig";
import styles from "./GlucoseChart.module.css";

interface GlucoseChartProps {
  /** Pass to enable self-fetching day-by-day navigation. */
  patientId?: number;
  /** Fallback readings when patientId is not provided (e.g. demo/patient page). */
  readings?: GlucoseReading[];
  title?: string;
  /** Called whenever the day offset changes (0 = latest, 1 = 1 day ago, …). */
  onOffsetChange?: (offset: number, latestDay: Date | null) => void;
  /** Called once the latest anchor day is resolved from the API. */
  onLatestDayResolved?: (day: Date) => void;
}

export default function GlucoseChart({
  patientId,
  readings: fallbackReadings,
  title,
  onOffsetChange,
  onLatestDayResolved,
}: GlucoseChartProps) {
  const { unit } = useGlucoseUnit();
  const { ranges: thresholds } = useGlucoseRanges();

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
  const [loading, setLoading] = useState(false);

  /** Fetch the window [startOfDay(anchor - offsetDays), endOfDay(anchor - offsetDays)]. */
  const fetchByAnchor = useCallback(
    async (anchor: Date, offsetDays: number) => {
      if (!patientId) return;
      setLoading(true);
      try {
        const base = subDays(anchor, offsetDays);
        const resp = await getGlucoseReadings(patientId, {
          start: startOfDay(base).toISOString(),
          end: endOfDay(base).toISOString(),
        });
        setFetchedReadings(resp.readings);
      } catch {
        setFetchedReadings([]);
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
        }
      })
      .catch(() => {
        if (!cancelled) setFetchedReadings([]);
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

  // Decide which readings to display
  const activeReadings = patientId ? (fetchedReadings ?? []) : (fallbackReadings ?? []);

  const chartData = activeReadings
    .slice()
    .map((r) => {
      const d = new Date(r.timestamp);
      return {
        // Fractional hour: 08:30 → 8.5, used as the numeric X value
        hour: d.getHours() + d.getMinutes() / 60,
        time: format(d, "HH:mm"),
        fullTime: format(d, "MMM d, HH:mm"),
        glucose: convertGlucose(r.glucose_mmoll, unit),
        status: r.status,
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

            <span className={styles.dayLabel}>{displayDate}</span>

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
              contentStyle={{
                background: "var(--card-bg)",
                border: "1px solid var(--border)",
                borderRadius: "8px",
              }}
              formatter={(value: unknown) => [`${value} ${unit}`, "Glucose"]}
              labelFormatter={(_label: unknown, payload) => {
                const t = (payload?.[0]?.payload as { time?: string })?.time;
                return t ? `Time: ${t}` : '';
              }}
            />
            {/* key change forces re-render on day navigation; wipe overlay handles the visual transition */}
            <Line
              key={animationKey.current}
              type="monotone"
              dataKey="glucose"
              stroke="var(--primary)"
              strokeWidth={2}
              dot={false}
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
