"use client";

import { Activity, Droplets, AlertTriangle, FlaskConical } from "lucide-react";
import type { GlucoseReading, TimeInRange, HbA1c, Gmi } from "@/models/types";
import { useGlucoseUnit } from "@/controllers/GlucoseUnitContext";
import { formatGlucose } from "@/models/glucoseUnits";
import { useGlucoseRanges, type GlucoseRanges } from "@/controllers/GlucoseRangesContext";
import styles from "./PatientOverview.module.css";

interface PatientOverviewProps {
  patientName: string;
  patientId: string;
  patientAge: string | number | null;
  latestReading?: GlucoseReading;
  tir?: TimeInRange;
  anomalyCount?: number;
  averageGlucose?: number | null;
  timeRangeLast?: string;
  hba1c?: HbA1c;
  gmi?: Gmi;
}

function getGlucoseStatus(value: number, ranges: GlucoseRanges): string {
  if (value < ranges.veryLow) return "very_low";
  if (value < ranges.low) return "low";
  if (value <= ranges.high) return "in_range";
  if (value <= ranges.veryHigh) return "high";
  return "very_high";
}

function getStatusColor(status?: string): string {
  switch (status) {
    case "very_low":
    case "very_high":
      return "var(--danger)";
    case "low":
    case "high":
      return "var(--warning)";
    case "in_range":
      return "var(--success)";
    default:
      return "var(--text-secondary)";
  }
}

function getStatusLabel(status?: string): string {
  switch (status) {
    case "very_low":  return "Very Low";
    case "low":       return "Low";
    case "in_range":  return "In Range";
    case "high":      return "High";
    case "very_high": return "Very High";
    default:          return "Unknown";
  }
}

export default function PatientOverview({
  patientName,
  patientId,
  patientAge,
  latestReading,
  tir,
  anomalyCount = 0,
  averageGlucose,
  timeRangeLast = "2w",
  hba1c,
  gmi,
}: PatientOverviewProps) {
  const { unit } = useGlucoseUnit();
  const { ranges: glucoseRanges } = useGlucoseRanges();

  const latestStatus = latestReading
    ? getGlucoseStatus(latestReading.glucose_mmoll, glucoseRanges)
    : undefined;

  const averageStatus = averageGlucose != null
    ? getGlucoseStatus(averageGlucose, glucoseRanges)
    : undefined;

  return (
    <div className={styles.card}>
      <div className={styles.header}>
        <h3 className={styles.name}>{patientName}</h3>
        <div className={styles.headerMeta}>
          <span className={styles.id}>{patientId}</span>
          <span className={styles.age}>Age: {patientAge} yo</span>
        </div>
      </div>

      <div className={styles.metrics}>
        {/* Current glucose */}
        <div className={styles.metric}>
          <div className={styles.metricIcon}>
            <Droplets size={18} />
          </div>
          <div>
            <div className={styles.metricLabel}>Latest Glucose</div>
            <div
              className={styles.metricValue}
              style={{ color: getStatusColor(latestStatus) }}
            >
              {latestReading
                ? formatGlucose(latestReading.glucose_mmoll, unit)
                : "—"}
            </div>
            <div
              className={styles.metricStatus}
              style={{ color: getStatusColor(latestStatus) }}
            >
              {getStatusLabel(latestStatus)}
            </div>
          </div>
        </div>

        {/* Time in range */}
        <div className={styles.metric}>
          <div className={styles.metricIcon}>
            <Activity size={18} />
          </div>
          <div>
            <div className={styles.metricLabel}>Time in Range</div>
            <div className={styles.metricValue}>
              {tir ? `${tir.in_range_pct}%` : "—"}
            </div>
          </div>
        </div>

        {/* Average Glucose */}
        {averageGlucose != null && (
          <div className={styles.metric}>
            <div className={styles.metricIcon}>
              <Droplets size={18} />
            </div>
            <div>
            <div className={styles.metricLabel}>Avg Glucose ({timeRangeLast})</div>
            <div
              className={styles.metricValue}
              style={{ color: getStatusColor(averageStatus) }}
            >
              {averageGlucose != null
                ? formatGlucose(averageGlucose, unit)
                : "—"}
            </div>
            <div
              className={styles.metricStatus}
              style={{ color: getStatusColor(averageStatus) }}
            >
              {getStatusLabel(averageStatus)}
            </div>
          </div>
        </div>)}

        {/* HbA1c */}
        {hba1c != null && (
          <div className={styles.metric}>
            <div className={styles.metricIcon}>
              <FlaskConical size={18} />
            </div>
            <div>
              <div className={styles.metricLabel}>HbA1c ({timeRangeLast})</div>
              <div className={styles.metricValue}>
                {hba1c.percent.toFixed(1)}%
              </div>
              <div className={styles.metricStatus} style={{ color: "var(--text-secondary)" }}>
                {Math.round(hba1c.mmol_per_mol)} mmol/mol
              </div>
            </div>
          </div>
        )}

        {/* GMI */}
        {gmi != null && (
          <div className={styles.metric}>
            <div className={styles.metricIcon}>
              <FlaskConical size={18} />
            </div>
            <div>
              <div className={styles.metricLabel}>GMI ({timeRangeLast})</div>
              <div className={styles.metricValue}>
                {gmi.gmi.toFixed(1)}%
              </div>
            </div>
          </div>
        )}

        {/* Anomalies */}
        <div className={styles.metric}>
          <div
            className={styles.metricIcon}
            style={anomalyCount > 0 ? { color: "var(--danger)" } : undefined}
          >
            <AlertTriangle size={18} />
          </div>
          <div>
            <div className={styles.metricLabel}>Anomalies</div>
            <div
              className={styles.metricValue}
              style={anomalyCount > 0 ? { color: "var(--danger)" } : undefined}
            >
              {anomalyCount}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
