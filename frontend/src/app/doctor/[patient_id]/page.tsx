"use client";

import { useMemo } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import GlucoseChart from "@/components/GlucoseChart";
import TIRBarChart from "@/components/TIRBarChart";
import PatientOverview from "@/components/PatientOverview";
import AnomalyAlert from "@/components/AnomalyAlert";
import {
  DEMO_ANOMALIES,
  generateDemoReadings,
  getDemoPatientByExternalId,
} from "@/data/demo-data";
import styles from "./patient-detail.module.css";

/**
 * Doctor — Patient Detail Page  (/doctor/[patient_id])
 *
 * Shows the full glucose + TIR + anomaly view for a single patient,
 * accessible from the Doctor Dashboard by clicking a patient card.
 * The [patient_id] segment matches the patient's external_id.
 *
 * In production, data will be fetched from the API using the patient ID.
 */
export default function DoctorPatientDetail() {
  const { patient_id } = useParams<{ patient_id: string }>();

  // Look up the patient in the demo data using the external_id from the URL
  const entry = getDemoPatientByExternalId(patient_id);
  const readings = useMemo(() => generateDemoReadings(), []);

  if (!entry) {
    return (
      <div className={styles.notFound}>
        <p>Patient <code>{patient_id}</code> not found.</p>
        <Link href="/doctor" className={styles.backLink}>
          <ArrowLeft size={16} /> Back to Doctor Dashboard
        </Link>
      </div>
    );
  }

  const { patient, tir } = entry;
  const anomalies = DEMO_ANOMALIES[patient.id] ?? [];

  return (
    <div className={styles.dashboard}>
      {/* Back navigation */}
      <Link href="/doctor" className={styles.backLink}>
        <ArrowLeft size={16} />
        Back to Doctor Dashboard
      </Link>

      <h2 className={styles.pageTitle}>Patient Detail View</h2>

      {/* Overview card */}
      <PatientOverview
        patientName={patient.name}
        patientId={patient.external_id}
        patientAge={patient.age != null ? String(patient.age) : "??"}
        latestReading={readings[readings.length - 1]}
        tir={tir}
        anomalyCount={anomalies.filter((a) => !a.is_acknowledged).length}
      />

      {/* Anomaly alerts */}
      {anomalies.length > 0 && (
        <AnomalyAlert
          anomalies={anomalies}
          onAcknowledge={(id) => {
            console.log("Acknowledge anomaly:", id);
            // TODO: call acknowledgeAnomaly(id) via API
          }}
        />
      )}

      {/* Charts */}
      <div className={styles.chartsGrid}>
        <GlucoseChart readings={readings} title="24-Hour Glucose Trace" />
        <TIRBarChart tir={tir} />
      </div>
    </div>
  );
}
