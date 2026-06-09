/**
 * CONTROLLER — Doctor Patient Detail
 *
 * Owns all state and data for /doctor/[patient_id].
 * Accepts the external_id from the URL segment, resolves the patient,
 * then loads glucose readings, TIR, and anomalies from the backend.
 *
 * API calls (see models/api.ts):
 *   GET api/patient/by-external/{externalId} → resolve external_id → patient
 *   GET api/glucose/{id}                     → glucose readings
 *   GET api/glucose/{id}/tir                 → time-in-range stats
 *   GET api/anomaly/{id}                     → anomaly list
 *   POST api/anomaly/{anomalyId}/acknowledge → acknowledge anomaly
 */
"use client";

import { useState, useEffect, useCallback } from "react";
import type { Patient, GlucoseReading, TimeInRange, AnomalyDetection } from "@/models/types";
import {
  getPatientByExternalId,
  getGlucoseReadings,
  getTimeInRange,
  getAnomalies,
  acknowledgeAnomaly,
} from "@/models/api";

type State =
  | { status: "loading" }
  | { status: "not_found" }
  | { status: "error"; message: string }
  | {
      status: "ready";
      patient: Patient;
      readings: GlucoseReading[];
      multiWeekReadings: GlucoseReading[];
      tir: TimeInRange | null;
      anomalies: AnomalyDetection[];
    };

export function usePatientDetailController(externalId: string) {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        setState({ status: "loading" });

        // 1. Resolve external_id → patient object via dedicated endpoint
        let patient;
        try {
          patient = await getPatientByExternalId(externalId);
        } catch (err: unknown) {
          if (cancelled) return;
          // axios 404 → not_found; anything else → error
          const status = (err as { response?: { status?: number } })?.response?.status;
          if (status === 404) {
            setState({ status: "not_found" });
          } else {
            setState({ status: "error", message: err instanceof Error ? err.message : "Failed to load patient" });
          }
          return;
        }

        if (cancelled) return;

        // 2. Fetch all data for this patient in parallel
        // Start date for multi-week view: 4 weeks ago
        const fourWeeksAgo = new Date(Date.now() - 4 * 7 * 24 * 60 * 60 * 1000).toISOString();

        const [readingsResult, multiWeekResult, tirResult, anomaliesResult] =
          await Promise.allSettled([
            getGlucoseReadings(patient.id, { limit: 288 }),          // last 24 h (5-min intervals)
            getGlucoseReadings(patient.id, { start: fourWeeksAgo }), // last 4 weeks for multi-weekly chart
            getTimeInRange(patient.id),
            getAnomalies(patient.id, { limit: 50 }),
          ]);

        if (cancelled) return;

        setState({
          status: "ready",
          patient,
          readings:
            readingsResult.status === "fulfilled"
              ? readingsResult.value.readings
              : [],
          multiWeekReadings:
            multiWeekResult.status === "fulfilled"
              ? multiWeekResult.value.readings
              : [],
          tir:
            tirResult.status === "fulfilled" ? tirResult.value : null,
          anomalies:
            anomaliesResult.status === "fulfilled"
              ? anomaliesResult.value.anomalies
              : [],
        });
      } catch (err) {
        if (!cancelled) {
          setState({
            status: "error",
            message:
              err instanceof Error ? err.message : "Failed to load patient data",
          });
        }
      }
    }

    load();
    return () => { cancelled = true; };
  }, [externalId]);

  const handleAcknowledge = useCallback(
    async (anomalyId: number) => {
      try {
        await acknowledgeAnomaly(anomalyId);
        // Optimistically update local state
        setState((prev) => {
          if (prev.status !== "ready") return prev;
          return {
            ...prev,
            anomalies: prev.anomalies.map((a) =>
              a.id === anomalyId ? { ...a, is_acknowledged: true } : a
            ),
          };
        });
      } catch (err) {
        console.error("Failed to acknowledge anomaly:", anomalyId, err);
      }
    },
    []
  );

  // ── Return shape ─────────────────────────────────────────

  if (state.status === "loading") {
    return {
      notFound: false as const,
      loading: true as const,
      error: null,
      patient: null,
      readings: [],
      multiWeekReadings: [] as GlucoseReading[],
      tir: null,
      anomalies: [],
      latestReading: undefined,
      unacknowledgedCount: 0,
      handleAcknowledge,
    };
  }

  if (state.status === "not_found") {
    return { notFound: true as const, loading: false, error: null, patient: null, readings: [], multiWeekReadings: [] as GlucoseReading[], tir: null, anomalies: [], latestReading: undefined, unacknowledgedCount: 0, handleAcknowledge };
  }

  if (state.status === "error") {
    return {
      notFound: false as const,
      loading: false as const,
      error: state.message,
      patient: null,
      readings: [],
      multiWeekReadings: [] as GlucoseReading[],
      tir: null,
      anomalies: [],
      latestReading: undefined,
      unacknowledgedCount: 0,
      handleAcknowledge,
    };
  }

  const { patient, readings, multiWeekReadings, tir, anomalies } = state;

  return {
    notFound: false as const,
    loading: false as const,
    error: null,
    patient,
    tir,
    readings,
    multiWeekReadings,
    anomalies,
    latestReading: readings.length > 0 ? readings[0] : undefined, // ordered descending by backend
    unacknowledgedCount: anomalies.filter((a) => !a.is_acknowledged).length,
    handleAcknowledge,
  };
}
