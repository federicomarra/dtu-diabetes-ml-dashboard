"use client";

import Link from "next/link";
import PatientOverview from "@/components/PatientOverview";
import type { Patient, GlucoseReading, TimeInRange } from "@/types";
import styles from "./doctor.module.css";
import { DEMO_PATIENTS } from "@/data/demo-data";

/**
 * Doctor Dashboard — multi-patient overview for clinicians.
 *
 * Shows summary cards for all patients with key metrics.
 * In production, data comes from the API.
 */

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
          <Link
            key={patient.id}
            href={`/doctor/${patient.external_id}`}
            className={styles.cardLink}
          >
            <PatientOverview
              patientName={patient.name}
              patientId={patient.external_id}
              patientAge={patient.age != null ? String(patient.age) : "??"}
              latestReading={latestReading}
              tir={tir}
              anomalyCount={anomalyCount}
            />
          </Link>
        ))}
      </div>
    </div>
  );
}
