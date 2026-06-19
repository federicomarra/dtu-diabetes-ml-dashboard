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
}

// ─── Random demo data generator ──────────────────────────────────────────────

function generateDemoData(): ChartPoint[] {
  const points: ChartPoint[] = [];
  // Simulate a basal rate throughout the day + bolus at meal times
  for (let h = 0; h < 24; h++) {
    const basalRate = 0.8 + Math.sin((h / 24) * Math.PI) * 0.3 + (Math.random() - 0.5) * 0.1;
    const isMealTime = h === 7 || h === 12 || h === 19;
    points.push({
      hour: h,
      time: `${String(h).padStart(2, "0")}:00`,
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
  // Build a map of hours with basal/bolus values
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
}: InsulinDailyChartProps) {
  const [latestDay, setLatestDay] = useState<Date | null>(null);
  const [offset, setOffset] = useState(0);
  const [fetchedEvents, setFetchedEvents] = useState<InsulinEvent[] | null>(null);
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

  useEffect(() => {
    if (!patientId) return;
    let cancelled = false;
    setLoading(true);
    getInsulins(patientId, { last: "1d" })
      .then((resp) => {
        if (cancelled) return;
        setFetchedEvents(resp.insulins);
        if (resp.insulins.length > 0) {
          const latest = resp.insulins.reduce((a, b) =>
            new Date(a.timestamp) > new Date(b.timestamp) ? a : b
          );
          setLatestDay(startOfDay(new Date(latest.timestamp)));
        }
      })
      .catch(() => {
        if (!cancelled) setFetchedEvents([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [patientId]);

  const handlePrev = () => {
    if (!latestDay) return;
    const next = offset + 1;
    setOffset(next);
    fetchByAnchor(latestDay, next);
  };

  const handleNext = () => {
    if (!latestDay || offset === 0) return;
    const next = offset - 1;
    setOffset(next);
    fetchByAnchor(latestDay, next);
  };

  const handleGoLatest = () => {
    if (!latestDay || offset === 0) return;
    setOffset(0);
    fetchByAnchor(latestDay, 0);
  };

  // Which data source to use
  const activeEvents = patientId ? (fetchedEvents ?? []) : (fallbackEvents ?? []);
  const chartData: ChartPoint[] =
    patientId
      ? (activeEvents.length > 0 ? toChartPoints(activeEvents) : [])
      : (fallbackEvents ? toChartPoints(fallbackEvents) : generateDemoData());

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

        {patientId && (
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
              disabled={!latestDay}
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
                `${value} U`,
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
              type="monotone"
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
