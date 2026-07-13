/**
 * CONTROLLER — Doctor Dashboard
 *
 * Owns all state and data for /doctor.
 * Returns the patient list and aggregate stats loaded from the backend.
 *
 * API calls (see models/api.ts):
 *   GET api/patient/list?page=&perPage=
 *   GET api/glucose?id={patientId}&last={last}
 *   GET api/glucose/tir?id={patientId}&last={last}&{rangeParams}
 *   GET api/anomaly?id={patientId}&acknowledged=false
 */
"use client";

import { useState, useEffect, useRef } from "react";
import type { Patient, GlucoseReading, TimeInRange, HbA1c, AnomalyDetection } from "@/models/types";
import {
  getPatients,
  getLatestReading,
  getTimeInRange,
  getAnomalies,
  getAverageReading,
  getHbA1c,
} from "@/models/api";
import { useTimeRange } from "@/controllers/TimeRangeContext";
import { useGlucoseRanges } from "@/controllers/GlucoseRangesContext";

export interface PatientSummary {
  patient: Patient;
  latestReading: GlucoseReading | undefined;
  tir: TimeInRange | null;
  anomalyCount: number;
  anomalies: AnomalyDetection[];
  averageGlucose: number | null;
  hba1c: HbA1c | null;
}

export const PER_PAGE_OPTIONS = [20, 50, 100, 200] as const;
export type PerPageOption = (typeof PER_PAGE_OPTIONS)[number];

export function useDoctorController() {
  const { timeRange } = useTimeRange();
  const { ranges: glucoseRanges } = useGlucoseRanges();
  const [patients, setPatients] = useState<PatientSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [page, setPageRaw] = useState(1);
  const [perPage, setPerPageRaw] = useState<PerPageOption>(20);
  const [totalPatients, setTotalPatients] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const hasLoadedOnce = useRef(false);

  const [sortKey, setSortKey] = useState<"name" | "ext_id" | "age" | "anomalies" | "tir" | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc" | null>(null);

  const refresh = () => setRefreshTrigger((prev) => prev + 1);

  /** Change page — clamped to valid range. */
  const setPage = (p: number) =>
    setPageRaw(Math.max(1, Math.min(p, totalPages || 1)));

  /** Change per-page and reset to page 1. */
  const setPerPage = (pp: PerPageOption) => {
    setPerPageRaw(pp);
    setPageRaw(1);
  };

  /** Toggle sorting key with cycle: Ascending <-> Descending */
  const toggleSort = (key: "name" | "ext_id" | "age" | "anomalies" | "tir") => {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
    setPageRaw(1);
  };

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        if (!hasLoadedOnce.current) {
          setLoading(true);
        } else {
          setIsRefreshing(true);
        }
        setError(null);

        // 1. Fetch the patient list for the current page / per-page with sorting
        const paginatedPatients = await getPatients(
          page,
          perPage,
          sortKey || undefined,
          sortDir || undefined,
          timeRange,
          {
            low: glucoseRanges.low,
            high: glucoseRanges.high
          }
        );
        const patientList = paginatedPatients.patients;

        if (cancelled) return;

        setTotalPatients(paginatedPatients.total);
        setTotalPages(paginatedPatients.pages);

        // 2. For each patient, fetch their latest reading, TIR, anomaly count, and average glucose in parallel
        const summaries = await Promise.all(
          patientList.map(async (patient): Promise<PatientSummary> => {
            const [latestReading, tir, anomaliesResp, averageGlucoseResp, hba1cResp] = await Promise.allSettled([
              getLatestReading(patient.id),
              getTimeInRange(patient.id, {
                ...timeRange,
                VeryLow: glucoseRanges.veryLow,
                Low: glucoseRanges.low,
                High: glucoseRanges.high,
                VeryHigh: glucoseRanges.veryHigh,
              }),
              getAnomalies(patient.id, timeRange),
              getAverageReading(patient.id, timeRange),
              getHbA1c(patient.id, timeRange),
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
                  ? anomaliesResp.value.anomalies.filter((a) => !a.is_acknowledged).length
                  : 0,
              anomalies:
                anomaliesResp.status === "fulfilled"
                  ? anomaliesResp.value.anomalies
                  : [],
              averageGlucose:
                averageGlucoseResp.status === "fulfilled"
                  ? averageGlucoseResp.value
                  : null,
              hba1c:
                hba1cResp.status === "fulfilled"
                  ? hba1cResp.value
                  : null,
            };
          })
        );

        if (!cancelled) {
          setPatients(summaries);
          hasLoadedOnce.current = true;
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load patients");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
          setIsRefreshing(false);
        }
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [page, perPage, timeRange, glucoseRanges, refreshTrigger, sortKey, sortDir]);

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
    refresh,
    isRefreshing,
    // Sorting
    sortKey,
    sortDir,
    toggleSort,
  };
}
