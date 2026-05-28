/**
 * CONTROLLER — Doctor Dashboard
 *
 * Owns all state and data for /doctor.
 * Returns the patient list and aggregate stats loaded from the backend.
 *
 * API calls (see models/api.ts):
 *   GET api/patient/list
 *   GET api/glucose/{id}/latest
 *   GET api/glucose/{id}/tir
 *   GET api/anomaly/{id}?acknowledged=false
 */
"use client";

import { useState, useEffect } from "react";
import type { Patient, GlucoseReading, TimeInRange } from "@/models/types";
import {
  getPatients,
  getLatestReading,
  getTimeInRange,
  getAnomalies,
} from "@/models/api";

export interface PatientSummary {
  patient: Patient;
  latestReading: GlucoseReading | undefined;
  tir: TimeInRange | null;
  anomalyCount: number;
}

export function useDoctorController() {
  const [patients, setPatients] = useState<PatientSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        setLoading(true);
        setError(null);

        // 1. Fetch the patient list
        const paginatedPatients = await getPatients(1, 50);
        const patientList = paginatedPatients.patients;

        if (cancelled) return;

        // 2. For each patient, fetch their latest reading, TIR, and anomaly count in parallel
        const summaries = await Promise.all(
          patientList.map(async (patient): Promise<PatientSummary> => {
            const [latestReading, tir, anomaliesResp] = await Promise.allSettled([
              getLatestReading(patient.id),
              getTimeInRange(patient.id),
              getAnomalies(patient.id, { acknowledged: false }),
            ]);

            return {
              patient,
              latestReading:
                latestReading.status === "fulfilled"
                  ? latestReading.value
                  : undefined,
              tir:
                tir.status === "fulfilled" ? tir.value : null,
              anomalyCount:
                anomaliesResp.status === "fulfilled"
                  ? anomaliesResp.value.count
                  : 0,
            };
          })
        );

        if (!cancelled) {
          setPatients(summaries);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load patients");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => { cancelled = true; };
  }, []);

  const totalAlerts = patients.reduce((sum, p) => sum + p.anomalyCount, 0);

  return {
    patients,
    patientCount: patients.length,
    totalAlerts,
    loading,
    error,
  };
}
