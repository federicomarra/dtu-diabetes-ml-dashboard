"use client";

import GlucoseChart from "@/views/GlucoseChart/GlucoseChart";
import TIRChart from "@/views/TIRChart/TIRChart";
import PatientOverview from "@/views/PatientOverview/PatientOverview";
import AnomalyAlert from "@/views/AnomalyAlert/AnomalyAlert";
import { usePatientController } from "@/controllers/usePatientController";
import styles from "./patient.module.css";

/**
 * Patient Dashboard — thin shell.
 * All data and business logic lives in usePatientController.
 */
export default function PatientDashboard() {
  const {
    patient,
    readings,
    tir,
    anomalies,
    latestReading,
    unacknowledgedCount,
    handleAcknowledge,
  } = usePatientController();

  return (
    <div className={styles.dashboard}>
      <h2 className={styles.pageTitle}>Patient Dashboard</h2>

      <PatientOverview
        patientName={patient.name}
        patientId={patient.external_id}
        patientAge={patient.age}
        latestReading={latestReading}
        tir={tir}
        anomalyCount={unacknowledgedCount}
      />

      <AnomalyAlert anomalies={anomalies} onAcknowledge={handleAcknowledge} />

      <div className={styles.chartsGrid}>
        <GlucoseChart readings={readings} title="24-Hour Glucose Trace" />
        <TIRChart tir={tir} />
      </div>
    </div>
  );
}
