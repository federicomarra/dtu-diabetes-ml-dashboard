"use client";

import Link from "next/link";
import PatientOverview from "@/views/PatientOverview/PatientOverview";
import { useDoctorController } from "@/controllers/useDoctorController";
import styles from "./doctor.module.css";

/**
 * Doctor Dashboard — thin shell.
 * All data and business logic lives in useDoctorController.
 */
export default function DoctorDashboard() {
  const { patients, patientCount, totalAlerts, loading, error } =
    useDoctorController();

  if (loading) {
    return (
      <div className={styles.dashboard}>
        <div className={styles.header}>
          <h2 className={styles.pageTitle}>Doctor Dashboard</h2>
          <p className={styles.subtitle}>Loading patients…</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className={styles.dashboard}>
        <div className={styles.header}>
          <h2 className={styles.pageTitle}>Doctor Dashboard</h2>
          <p className={styles.subtitle} style={{ color: "var(--color-high)" }}>
            Error: {error}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.dashboard}>
      <div className={styles.header}>
        <h2 className={styles.pageTitle}>Doctor Dashboard</h2>
        <p className={styles.subtitle}>
          {patientCount} patients • {totalAlerts} total alerts
        </p>
      </div>

      <div className={styles.patientsGrid}>
        {patients.map(({ patient, latestReading, tir, anomalyCount }) => (
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
              tir={tir ?? undefined}
              anomalyCount={anomalyCount}
            />
          </Link>
        ))}
      </div>
    </div>
  );
}
