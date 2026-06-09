"use client";

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
import { format } from "date-fns";
import type { GlucoseReading } from "@/models/types";
import { useGlucoseUnit } from "@/controllers/GlucoseUnitContext";
import { useGlucoseRanges } from "@/controllers/GlucoseRangesContext";
import { useTimeRange, formatTimeRangeFriendly } from "@/controllers/TimeRangeContext";
import { convertGlucose } from "@/models/glucoseUnits";
import {
  LOW_THRESHOLD,
  HIGH_THRESHOLD,
  VERY_HIGH_THRESHOLD,
  CHART_DOMAIN_MIN,
  CHART_DOMAIN_MAX,
} from "@/models/glucoseConfig";
import type { CustomThresholds } from "@/views/TIRChart/TIRChart";
import styles from "./GlucoseChart.module.css";

interface GlucoseChartProps {
  readings?: GlucoseReading[];
  title?: string;
}

export default function GlucoseChart({
  readings,
  title,
}: GlucoseChartProps) {
  const { unit } = useGlucoseUnit();
  const { ranges: thresholds } = useGlucoseRanges();
  const { timeRange } = useTimeRange();

  const chartData = (readings || [])
    .slice()
    .sort(
      (a, b) =>
        new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
    )
    .map((r) => ({
      time: format(new Date(r.timestamp), "HH:mm"),
      fullTime: format(new Date(r.timestamp), "MMM d, HH:mm"),
      glucose: convertGlucose(r.glucose_mmoll, unit),
      status: r.status,
    }));

  const low      = convertGlucose(thresholds?.low      ?? LOW_THRESHOLD,       unit);
  const high     = convertGlucose(thresholds?.high     ?? HIGH_THRESHOLD,      unit);
  const veryHigh = convertGlucose(thresholds?.veryHigh ?? VERY_HIGH_THRESHOLD, unit);
  const domainMin = convertGlucose(CHART_DOMAIN_MIN, unit);
  const domainMax = convertGlucose(CHART_DOMAIN_MAX, unit);

  const friendlyTime = formatTimeRangeFriendly(timeRange);
  const chartTitle = title || `Glucose trace of the ${friendlyTime}`;

  return (
    <div className={styles.container}>
      <h3 className={styles.title}>{chartTitle}</h3>
      <ResponsiveContainer width="100%" height={320}>
        <LineChart data={chartData} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />

          {/* Target range shading */}
          <ReferenceArea
            y1={low}
            y2={high}
            fill="var(--success)"
            fillOpacity={0.08}
          />

          {/* Clinical threshold lines */}
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
            dataKey="time"
            tick={{ fontSize: 11 }}
            interval="preserveStartEnd"
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
            labelFormatter={(label: unknown) => `Time: ${label}`}
          />
          <Line
            type="monotone"
            dataKey="glucose"
            stroke="var(--primary)"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, fill: "var(--primary)" }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
