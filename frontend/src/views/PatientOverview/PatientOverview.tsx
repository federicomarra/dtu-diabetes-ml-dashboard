"use client";

import { Activity, Droplets, AlertTriangle } from "lucide-react";
import type { GlucoseReading, TimeInRange } from "@/models/types";
import { useGlucoseUnit } from "@/controllers/GlucoseUnitContext";
import { formatGlucose } from "@/models/glucoseUnits";
import styles from "./PatientOverview.module.css";

interface PatientOverviewProps {
  patientName: string;
  patientId: string;
  patientAge: string | number | null;
  latestReading?: GlucoseReading;
  tir?: TimeInRange;
  anomalyCount?: number;
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
}: PatientOverviewProps) {
  const { unit } = useGlucoseUnit();

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
            <div className={styles.metricLabel}>Current Glucose</div>
            <div
              className={styles.metricValue}
              style={{ color: getStatusColor(latestReading?.status) }}
            >
              {latestReading
                ? formatGlucose(latestReading.glucose_mmoll, unit)
                : "—"}
            </div>
            <div
              className={styles.metricStatus}
              style={{ color: getStatusColor(latestReading?.status) }}
            >
              {getStatusLabel(latestReading?.status)}
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
