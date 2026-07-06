"use client";

import { useState, useEffect, useCallback } from "react";
import {
  ComposedChart,
  Line,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { format, subDays, startOfDay, endOfDay } from "date-fns";
import type { InsulinEvent } from "@/models/types";
import { getInsulins } from "@/models/api";
import styles from "./InsulinDailyChart.module.css";

interface InsulinDailyChartProps {
  /** Pass to enable self-fetching day-by-day navigation. */
  patientId?: number;
  /** Fallback (demo) data when patientId is not provided. */
  events?: InsulinEvent[];
  /**
   * Controlled mode: when provided, the chart skips its own nav UI and
   * uses this offset (days before the glucose anchor).
   */
  syncOffset?: number;
  /** Controlled mode: the glucose chart's anchor day. */
  syncLatestDay?: Date | null;
  /**
   * Called once the component has resolved its own latestDay anchor
   * (only relevant in uncontrolled mode).
   */
  onLatestDayResolved?: (day: Date) => void;
  /**
   * Called when the chart resolves whether it has data for the initial load.
   */
  onDataPresence?: (hasData: boolean) => void;
}

// ─── Random demo data generator ──────────────────────────────────────────────

function generateDemoData(): ChartPoint[] {
  const points: ChartPoint[] = [];
  for (let h = 0; h < 24; h++) {
    const basalRate = 0.8 + Math.sin((h / 24) * Math.PI) * 0.3 + (Math.random() - 0.5) * 0.1;
    const isMealTime = h === 7 || h === 12 || h === 19;
    points.push({
      hour: h,
      time: `${String(h).padStart(2, "00")}:00`,
      basal: parseFloat(basalRate.toFixed(2)),
      bolus: isMealTime ? parseFloat((2 + Math.random() * 4).toFixed(2)) : null,
    });
  }
  return points;
}

// ─── Chart data shape ─────────────────────────────────────────────────────────

interface ChartPoint {
  hour: number;
  time: string;
  basal: number | null;
  bolus: number | null;
}

function toChartPoints(events: InsulinEvent[]): ChartPoint[] {
  const map = new Map<number, ChartPoint>();
  for (const e of events) {
    const d = new Date(e.timestamp);
    const hour = d.getHours() + d.getMinutes() / 60;
    const hourKey = Math.floor(hour);
    const existing = map.get(hourKey) ?? {
      hour: hourKey,
      time: format(d, "HH:mm"),
      basal: null,
      bolus: null,
    };
    if (e.event_type === "basal") {
      existing.basal = (existing.basal ?? 0) + e.units;
    } else {
      existing.bolus = (existing.bolus ?? 0) + e.units;
    }
    map.set(hourKey, existing);
  }
  return Array.from(map.values()).sort((a, b) => a.hour - b.hour);
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function InsulinDailyChart({
  patientId,
  events: fallbackEvents,
  syncOffset,
  syncLatestDay,
  onLatestDayResolved,
  onDataPresence,
}: InsulinDailyChartProps) {
  const isControlled = syncOffset !== undefined && syncLatestDay !== undefined;

  // Own state — only used in uncontrolled mode
  const [ownLatestDay, setOwnLatestDay] = useState<Date | null>(null);
  const [ownOffset, setOwnOffset] = useState(0);

  const latestDay = isControlled ? syncLatestDay : ownLatestDay;
  const offset = isControlled ? syncOffset : ownOffset;

  const [fetchedEvents, setFetchedEvents] = useState<InsulinEvent[] | null>(null);
  // true once initial (latest-day) fetch is done and had data
  const [hasDataOnLatestDay, setHasDataOnLatestDay] = useState<boolean | null>(null);
  const [initialised, setInitialised] = useState(false);
  const [loading, setLoading] = useState(false);

  const fetchByAnchor = useCallback(
    async (anchor: Date, offsetDays: number) => {
      if (!patientId) return;
      setLoading(true);
      try {
        const base = subDays(anchor, offsetDays);
        const resp = await getInsulins(patientId, {
          start: startOfDay(base).toISOString(),
          end: endOfDay(base).toISOString(),
        });
        setFetchedEvents(resp.insulins);
      } catch {
        setFetchedEvents([]);
      } finally {
        setLoading(false);
      }
    },
    [patientId]
  );

  // ── Initial load (resolve anchor from last 1d of insulin data) ──────────────
  useEffect(() => {
    if (!patientId) return;
    let cancelled = false;
    setLoading(true);
    getInsulins(patientId, { last: "1d" })
      .then((resp) => {
        if (cancelled) return;
        setFetchedEvents(resp.insulins);
        setInitialised(true);
        if (resp.insulins.length > 0) {
          const latest = resp.insulins.reduce((a, b) =>
            new Date(a.timestamp) > new Date(b.timestamp) ? a : b
          );
          const day = startOfDay(new Date(latest.timestamp));
          setOwnLatestDay(day);
          setHasDataOnLatestDay(true);
          onLatestDayResolved?.(day);
          onDataPresence?.(true);
        } else {
          setHasDataOnLatestDay(false);
          onDataPresence?.(false);
        }
      })
      .catch(() => {
        if (!cancelled) { setFetchedEvents([]); setInitialised(true); setHasDataOnLatestDay(false); onDataPresence?.(false); }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [patientId]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── In controlled mode: re-fetch whenever the parent's offset/anchor changes ─
  useEffect(() => {
    if (!isControlled || !syncLatestDay || !patientId || !initialised) return;
    fetchByAnchor(syncLatestDay, syncOffset!);
  }, [syncOffset, syncLatestDay]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Uncontrolled navigation ──────────────────────────────────────────────────
  const handlePrev = () => {
    if (!ownLatestDay) return;
    const next = ownOffset + 1;
    setOwnOffset(next);
    fetchByAnchor(ownLatestDay, next);
  };

  const handleNext = () => {
    if (!ownLatestDay || ownOffset === 0) return;
    const next = ownOffset - 1;
    setOwnOffset(next);
    fetchByAnchor(ownLatestDay, next);
  };

  const handleGoLatest = () => {
    if (!ownLatestDay || ownOffset === 0) return;
    setOwnOffset(0);
    fetchByAnchor(ownLatestDay, 0);
  };

  // ── Data ────────────────────────────────────────────────────────────────────
  const activeEvents = patientId ? (fetchedEvents ?? []) : (fallbackEvents ?? []);
  const chartData: ChartPoint[] =
    patientId
      ? (activeEvents.length > 0 ? toChartPoints(activeEvents) : [])
      : (fallbackEvents ? toChartPoints(fallbackEvents) : generateDemoData());

  // Hide the whole card only if the latest day itself has no data
  if (patientId && hasDataOnLatestDay === false) {
    return null;
  }

  const displayDate = (() => {
    if (activeEvents.length > 0) return format(new Date(activeEvents[0].timestamp), "EEE, MMM d yyyy");
    if (latestDay) return format(subDays(latestDay, offset), "EEE, MMM d yyyy");
    return "—";
  })();

  const isLatest = offset === 0;

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h3 className={styles.title}>Insulin daily trace</h3>

        {/* Navigation only shown in uncontrolled mode */}
        {patientId && !isControlled && (
          <div className={styles.dayNav}>
            {!isLatest && (
              <button
                id="insulin-chart-go-latest"
                className={styles.latestBtn}
                onClick={handleGoLatest}
                title="Jump to latest available day"
              >
                Latest ›
              </button>
            )}
            <button
              id="insulin-chart-prev-day"
              className={styles.navBtn}
              onClick={handlePrev}
              disabled={!ownLatestDay}
              title="Previous day"
              aria-label="Previous day"
            >
              ‹
            </button>
            <span className={styles.dayLabel}>{displayDate}</span>
            <button
              id="insulin-chart-next-day"
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

        {/* In controlled mode, show the date label (driven by glucose chart) */}
        {patientId && isControlled && (
          <span className={styles.dayLabel}>{displayDate}</span>
        )}
      </div>

      <div className={loading ? styles.chartLoading : undefined}>
        <ResponsiveContainer width="100%" height={280}>
          <ComposedChart data={chartData} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis
              dataKey="hour"
              type="number"
              domain={[0, 23]}
              ticks={Array.from({ length: 24 }, (_, i) => i)}
              tickFormatter={(h: number) => String(h)}
              tick={{ fontSize: 10 }}
              interval={0}
              angle={-45}
              textAnchor="end"
              height={50}
            />
            <YAxis
              tick={{ fontSize: 11 }}
              label={{
                value: "Units",
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
              formatter={(value: unknown, name) => [
                `${value} U${name === "basal" ? "/h" : ""}`,
                name === "basal" ? "Basal" : "Bolus",
              ]}
              labelFormatter={(_label: unknown, payload) => {
                const t = (payload?.[0]?.payload as { time?: string })?.time;
                return t ? `Time: ${t}` : "";
              }}
            />
            <Legend
              formatter={(value) => (value === "basal" ? "Basal (line)" : "Bolus (bar)")}
              wrapperStyle={{ fontSize: "0.8rem" }}
            />
            {/* Bolus as bars */}
            <Bar dataKey="bolus" fill="var(--primary)" opacity={0.8} radius={[3, 3, 0, 0]} />
            {/* Basal as line */}
            <Line
              type="stepAfter"
              dataKey="basal"
              stroke="var(--warning, #f59e0b)"
              strokeWidth={2}
              dot={false}
              connectNulls
            />
          </ComposedChart>
        </ResponsiveContainer>

        {chartData.length === 0 && !loading && (
          <p className={styles.noData}>No insulin data for this day.</p>
        )}
      </div>
    </div>
  );
}
