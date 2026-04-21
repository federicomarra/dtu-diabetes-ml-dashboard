"use client";

import { useMemo } from "react";
import GlucoseChart from "@/components/GlucoseChart";
import TIRBarChart from "@/components/TIRBarChart";
import PatientOverview from "@/components/PatientOverview";
import AnomalyAlert from "@/components/AnomalyAlert";
import type {
  Patient,
  GlucoseReading,
  TimeInRange,
  AnomalyDetection,
} from "@/types";
import { generateDemoReadings } from "@/data/demo-data";
import styles from "./patient.module.css";

/**
 * Patient Dashboard — shows glucose data, TIR, and alerts for a single patient.
 *
 * In production, the patient ID comes from authentication.
 * For now, we use demo data to show the UI structure.
 */

// Demo data for development (replace with API calls when backend is running)
const DEMO_PATIENT: Patient = {
  id: 1,
  external_id: "SIM_00001",
  name: "Demo patient 000001",
  age: 34,
};

const DEMO_TIR: TimeInRange = {
  patient_id: 1,
  total_readings: 288,
  very_low_pct: 1.2,
  low_pct: 3.5,
  in_range_pct: 72.1,
  high_pct: 18.4,
  very_high_pct: 4.8,
};

const DEMO_ANOMALIES: AnomalyDetection[] = [
  {
    id: 1,
    patient_id: 1,
    glucose_reading_id: 42,
    anomaly_type: "missed_bolus",
    confidence: 0.85,
    description: "Glucose at 14.7 mmol/L with no bolus in preceding 30 min",
    is_acknowledged: false,
    detected_at: new Date(Date.now() - 2 * 3600 * 1000).toISOString(),
  },
  {
    id: 2,
    patient_id: 1,
    glucose_reading_id: 100,
    anomaly_type: "late_bolus",
    confidence: 0.62,
    description: "Bolus administered 45 min after meal start",
    is_acknowledged: false,
    detected_at: new Date(Date.now() - 6 * 3600 * 1000).toISOString(),
  },
];

export default function PatientDashboard() {
  // TODO: Replace with API call when backend is running
  // import { getGlucoseReadings, getTimeInRange, getAnomalies } from "@/lib/api";
  const readings = useMemo(() => generateDemoReadings(), []);

  return (
    <div className={styles.dashboard}>
      <h2 className={styles.pageTitle}>Patient Dashboard</h2>

      {/* Overview card */}
      <PatientOverview
        patientName={DEMO_PATIENT.name}
        patientId={DEMO_PATIENT.external_id}
        patientAge={DEMO_PATIENT.age}
        latestReading={readings[readings.length - 1]}
        tir={DEMO_TIR}
        anomalyCount={DEMO_ANOMALIES.filter((a) => !a.is_acknowledged).length}
      />

      {/* Anomaly alerts */}
      <AnomalyAlert
        anomalies={DEMO_ANOMALIES}
        onAcknowledge={(id) => {
          console.log("Acknowledge anomaly:", id);
          // TODO: call acknowledgeAnomaly(id)
        }}
      />

      {/* Charts */}
      <div className={styles.chartsGrid}>
        <GlucoseChart readings={readings} title="24-Hour Glucose Trace" />
        <TIRBarChart tir={DEMO_TIR} />
      </div>
    </div>
  );
}
