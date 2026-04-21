/**
 * CONTROLLER — Doctor Dashboard
 *
 * Owns all state and data for /doctor.
 * Returns the patient list and aggregate stats.
 *
 * TODO: replace demo data with real API call:
 *   import { getPatients } from "@/models/api";
 */
"use client";

import { DEMO_PATIENTS } from "@/models/demoData";

export function useDoctorController() {
  const patients = DEMO_PATIENTS;

  const totalAlerts = patients.reduce((sum, p) => sum + p.anomalyCount, 0);

  return {
    patients,
    patientCount: patients.length,
    totalAlerts,
  };
}
