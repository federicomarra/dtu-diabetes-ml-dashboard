"use client";

import { useState, useCallback } from "react";
import GlucoseChart from "@/views/GlucoseChart/GlucoseChart";
import TIRChart, { DEFAULT_THRESHOLDS, type CustomThresholds } from "@/views/TIRChart/TIRChart";
import MultiWeeklyChart from "@/views/MultiWeeklyChart/MultiWeeklyChart";
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
    multiWeekReadings,
    tir,
    anomalies,
    latestReading,
    unacknowledgedCount,
    handleAcknowledge,
    averageGlucose,
  } = usePatientController();

  const [thresholds, setThresholds] = useState<CustomThresholds>(DEFAULT_THRESHOLDS);
  const handleThresholdsChange = useCallback((t: CustomThresholds) => setThresholds(t), []);

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
        averageGlucose={averageGlucose}
      />

      <AnomalyAlert anomalies={anomalies} onAcknowledge={handleAcknowledge} />

      <div className={styles.chartsGrid}>
        <GlucoseChart readings={readings} title="24-Hour Glucose Trace" thresholds={thresholds} />
        <TIRChart
          tir={tir}
          patientId={patient.id}
          thresholds={thresholds}
          onThresholdsChange={handleThresholdsChange}
        />
      </div>

      <MultiWeeklyChart readings={multiWeekReadings} thresholds={thresholds} />
    </div>
  );
}



