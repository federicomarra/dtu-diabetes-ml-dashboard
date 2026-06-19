"use client";

import { useState, useEffect, useCallback } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { format, subDays, startOfDay, endOfDay } from "date-fns";
import type { MealEvent } from "@/models/types";
import { getMeals } from "@/models/api";
import styles from "./CarboDailyChart.module.css";

interface CarboDailyChartProps {
  /** Pass to enable self-fetching day-by-day navigation. */
  patientId?: number;
  /** Fallback (demo) data when patientId is not provided. */
  events?: MealEvent[];
}

// ─── Random demo data generator ──────────────────────────────────────────────

function generateDemoData(): ChartPoint[] {
  const mealSlots: { hour: number; label: string }[] = [
    { hour: 7, label: "Breakfast" },
    { hour: 12, label: "Lunch" },
    { hour: 16, label: "Snack" },
    { hour: 19, label: "Dinner" },
  ];
  return mealSlots.map(({ hour, label }) => ({
    hour,
    time: `${String(hour).padStart(2, "0")}:00`,
    carbs: parseFloat((20 + Math.random() * 60).toFixed(1)),
    mealType: label,
  }));
}

// ─── Chart data shape ─────────────────────────────────────────────────────────

interface ChartPoint {
  hour: number;
  time: string;
  carbs: number;
  mealType: string;
}

function toChartPoints(events: MealEvent[]): ChartPoint[] {
  return events
    .map((e) => {
      const d = new Date(e.timestamp);
      return {
        hour: d.getHours() + d.getMinutes() / 60,
        time: format(d, "HH:mm"),
        carbs: e.carbs,
        mealType: e.meal_type ?? "unknown",
      };
    })
    .sort((a, b) => a.hour - b.hour);
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function CarboDailyChart({
  patientId,
  events: fallbackEvents,
}: CarboDailyChartProps) {
  const [latestDay, setLatestDay] = useState<Date | null>(null);
  const [offset, setOffset] = useState(0);
  const [fetchedEvents, setFetchedEvents] = useState<MealEvent[] | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchByAnchor = useCallback(
    async (anchor: Date, offsetDays: number) => {
      if (!patientId) return;
      setLoading(true);
      try {
        const base = subDays(anchor, offsetDays);
        const resp = await getMeals(patientId, {
          start: startOfDay(base).toISOString(),
          end: endOfDay(base).toISOString(),
        });
        setFetchedEvents(resp.meals);
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
    getMeals(patientId, { last: "1d" })
      .then((resp) => {
        if (cancelled) return;
        setFetchedEvents(resp.meals);
        if (resp.meals.length > 0) {
          const latest = resp.meals.reduce((a, b) =>
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
        <h3 className={styles.title}>Carbohydrates daily intake</h3>

        {patientId && (
          <div className={styles.dayNav}>
            {!isLatest && (
              <button
                id="carbo-chart-go-latest"
                className={styles.latestBtn}
                onClick={handleGoLatest}
                title="Jump to latest available day"
              >
                Latest ›
              </button>
            )}
            <button
              id="carbo-chart-prev-day"
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
              id="carbo-chart-next-day"
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
          <BarChart
            data={chartData}
            margin={{ top: 5, right: 10, bottom: 5, left: 0 }}
            barSize={20}
          >
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
                value: "g carbs",
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
              formatter={(value: unknown, _name, props) => {
                const meal = (props?.payload as { mealType?: string })?.mealType;
                return [`${value} g`, meal ? `Carbs (${meal})` : "Carbs"];
              }}
              labelFormatter={(_label: unknown, payload) => {
                const t = (payload?.[0]?.payload as { time?: string })?.time;
                return t ? `Time: ${t}` : "";
              }}
            />
            <Bar
              dataKey="carbs"
              fill="var(--success, #22c55e)"
              opacity={0.85}
              radius={[4, 4, 0, 0]}
            />
          </BarChart>
        </ResponsiveContainer>

        {chartData.length === 0 && !loading && (
          <p className={styles.noData}>No meal data for this day.</p>
        )}
      </div>
    </div>
  );
}
