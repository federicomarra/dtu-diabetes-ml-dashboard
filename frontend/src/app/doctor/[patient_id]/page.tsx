"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import GlucoseChart from "@/views/GlucoseChart/GlucoseChart";
import TIRChart from "@/views/TIRChart/TIRChart";
import PatientOverview from "@/views/PatientOverview/PatientOverview";
import AnomalyAlert from "@/views/AnomalyAlert/AnomalyAlert";
import { usePatientDetailController } from "@/controllers/usePatientDetailController";
import styles from "./patient-detail.module.css";

/**
 * Doctor — Patient Detail Page (/doctor/[patient_id]) — thin shell.
 * All data and business logic lives in usePatientDetailController.
 */
export default function DoctorPatientDetail() {
  const { patient_id } = useParams<{ patient_id: string }>();
  const ctrl = usePatientDetailController(patient_id);

  if (ctrl.notFound) {
    return (
      <div className={styles.notFound}>
        <p>Patient <code>{patient_id}</code> not found.</p>
        <Link href="/doctor" className={styles.backLink}>
          <ArrowLeft size={16} /> Back to Doctor Dashboard
        </Link>
      </div>
    );
  }

  const { patient, tir, readings, anomalies, latestReading, handleAcknowledge } = ctrl;

  return (
    <div className={styles.dashboard}>
      <Link href="/doctor" className={styles.backLink}>
        <ArrowLeft size={16} />
        Back to Doctor Dashboard
      </Link>

      <h2 className={styles.pageTitle}>Patient Detail View</h2>

      <PatientOverview
        patientName={patient.name}
        patientId={patient.external_id}
        patientAge={patient.age != null ? String(patient.age) : "??"}
        latestReading={latestReading}
        tir={tir}
        anomalyCount={anomalies.filter((a) => !a.is_acknowledged).length}
      />

      {anomalies.length > 0 && (
        <AnomalyAlert anomalies={anomalies} onAcknowledge={handleAcknowledge} />
      )}

      <div className={styles.chartsGrid}>
        <GlucoseChart readings={readings} title="24-Hour Glucose Trace" />
        <TIRChart tir={tir} />
      </div>
    </div>
  );
}
