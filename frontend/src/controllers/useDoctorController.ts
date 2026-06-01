/**
 * CONTROLLER — Doctor Dashboard
 *
 * Owns all state and data for /doctor.
 * Returns the patient list and aggregate stats loaded from the backend.
 *
 * API calls (see models/api.ts):
 *   GET api/patient/list?page=&per_page=
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

export const PER_PAGE_OPTIONS = [20, 50, 100, 200] as const;
export type PerPageOption = (typeof PER_PAGE_OPTIONS)[number];

export function useDoctorController() {
  const [patients, setPatients] = useState<PatientSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [page, setPageRaw] = useState(1);
  const [perPage, setPerPageRaw] = useState<PerPageOption>(20);
  const [totalPatients, setTotalPatients] = useState(0);
  const [totalPages, setTotalPages] = useState(1);

  /** Change page — clamped to valid range. */
  const setPage = (p: number) =>
    setPageRaw((prev) => Math.max(1, Math.min(p, totalPages || 1)));

  /** Change per-page and reset to page 1. */
  const setPerPage = (pp: PerPageOption) => {
    setPerPageRaw(pp);
    setPageRaw(1);
  };

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        setLoading(true);
        setError(null);

        // 1. Fetch the patient list for the current page / per-page
        const paginatedPatients = await getPatients(page, perPage);
        const patientList = paginatedPatients.patients;

        if (cancelled) return;

        setTotalPatients(paginatedPatients.total);
        setTotalPages(paginatedPatients.pages);

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
              tir: tir.status === "fulfilled" ? tir.value : null,
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
    return () => {
      cancelled = true;
    };
  }, [page, perPage]);

  const totalAlerts = patients.reduce((sum, p) => sum + p.anomalyCount, 0);

  return {
    patients,
    patientCount: patients.length,
    totalPatients,
    totalAlerts,
    loading,
    error,
    // Pagination
    page,
    perPage,
    totalPages,
    setPage,
    setPerPage,
  };
}
