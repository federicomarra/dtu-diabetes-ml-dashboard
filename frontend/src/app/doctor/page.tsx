"use client";

import PatientOverview from "@/components/PatientOverview";
import type { Patient, GlucoseReading, TimeInRange } from "@/types";
import styles from "./doctor.module.css";

/**
 * Doctor Dashboard — multi-patient overview for clinicians.
 *
 * Shows summary cards for all patients with key metrics.
 * In production, data comes from the API.
 */

// Demo data for development
const DEMO_PATIENTS: Array<{
  patient: Patient;
  latestReading: GlucoseReading;
  tir: TimeInRange;
  anomalyCount: number;
}> = [
  {
    patient: {
      id: 1, external_id: "SIM_001", name: "Alice Johnson",
      date_of_birth: "1990-05-15", diabetes_type: "T1D",
      diagnosis_date: "2005-03-20", created_at: new Date().toISOString(),
    },
    latestReading: {
      id: 1, patient_id: 1, timestamp: new Date().toISOString(),
      glucose_mgdl: 145, source: "simulated", status: "in_range",
    },
    tir: {
      patient_id: 1, total_readings: 288,
      very_low_pct: 1.2, low_pct: 3.5, in_range_pct: 72.1,
      high_pct: 18.4, very_high_pct: 4.8,
    },
    anomalyCount: 2,
  },
  {
    patient: {
      id: 2, external_id: "SIM_002", name: "Bob Smith",
      date_of_birth: "1985-11-08", diabetes_type: "T1D",
      diagnosis_date: "2000-06-12", created_at: new Date().toISOString(),
    },
    latestReading: {
      id: 2, patient_id: 2, timestamp: new Date().toISOString(),
      glucose_mgdl: 95, source: "simulated", status: "in_range",
    },
    tir: {
      patient_id: 2, total_readings: 288,
      very_low_pct: 0.5, low_pct: 2.1, in_range_pct: 85.3,
      high_pct: 10.2, very_high_pct: 1.9,
    },
    anomalyCount: 0,
  },
  {
    patient: {
      id: 3, external_id: "SIM_003", name: "Clara Andersen",
      date_of_birth: "1998-02-22", diabetes_type: "T1D",
      diagnosis_date: "2010-09-01", created_at: new Date().toISOString(),
    },
    latestReading: {
      id: 3, patient_id: 3, timestamp: new Date().toISOString(),
      glucose_mgdl: 268, source: "simulated", status: "very_high",
    },
    tir: {
      patient_id: 3, total_readings: 288,
      very_low_pct: 3.1, low_pct: 5.2, in_range_pct: 55.8,
      high_pct: 22.4, very_high_pct: 13.5,
    },
    anomalyCount: 5,
  },
  {
    patient: {
      id: 4, external_id: "SIM_004", name: "David Nielsen",
      date_of_birth: "1975-07-30", diabetes_type: "T1D",
      diagnosis_date: "1990-04-15", created_at: new Date().toISOString(),
    },
    latestReading: {
      id: 4, patient_id: 4, timestamp: new Date().toISOString(),
      glucose_mgdl: 62, source: "simulated", status: "low",
    },
    tir: {
      patient_id: 4, total_readings: 288,
      very_low_pct: 4.5, low_pct: 8.3, in_range_pct: 64.7,
      high_pct: 16.1, very_high_pct: 6.4,
    },
    anomalyCount: 3,
  },
];

export default function DoctorDashboard() {
  return (
    <div className={styles.dashboard}>
      <div className={styles.header}>
        <h2 className={styles.pageTitle}>Doctor Dashboard</h2>
        <p className={styles.subtitle}>
          {DEMO_PATIENTS.length} patients •{" "}
          {DEMO_PATIENTS.reduce((sum, p) => sum + p.anomalyCount, 0)} total alerts
        </p>
      </div>

      <div className={styles.patientsGrid}>
        {DEMO_PATIENTS.map(({ patient, latestReading, tir, anomalyCount }) => (
          <PatientOverview
            key={patient.id}
            patientName={patient.name}
            patientId={patient.external_id}
            latestReading={latestReading}
            tir={tir}
            anomalyCount={anomalyCount}
          />
        ))}
      </div>
    </div>
  );
}
