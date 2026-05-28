/**
 * CONTROLLER — Doctor Patient Detail
 *
 * Owns all state and data for /doctor/[patient_id].
 * Accepts the external_id from the URL segment, resolves the patient,
 * then loads glucose readings, TIR, and anomalies from the backend.
 *
 * API calls (see models/api.ts):
 *   GET api/patient/list               → resolve external_id → patient.id
 *   GET api/glucose/{id}               → glucose readings
 *   GET api/glucose/{id}/tir           → time-in-range stats
 *   GET api/anomaly/{id}               → anomaly list
 *   POST api/anomaly/{anomalyId}/acknowledge → acknowledge anomaly
 */
"use client";

import { useState, useEffect, useCallback } from "react";
import type { Patient, GlucoseReading, TimeInRange, AnomalyDetection } from "@/models/types";
import {
  getPatients,
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

        // 1. Resolve external_id → patient object
        // The backend does not expose a /patient/by-external-id endpoint,
        // so we fetch page 1 with a large perPage to find the patient.
        const paginatedPatients = await getPatients(1, 100);
        const patient = paginatedPatients.patients.find(
          (p) => p.external_id === externalId
        );

        if (cancelled) return;

        if (!patient) {
          setState({ status: "not_found" });
          return;
        }

        // 2. Fetch all data for this patient in parallel
        const [readingsResult, tirResult, anomaliesResult] =
          await Promise.allSettled([
            getGlucoseReadings(patient.id, { limit: 288 }), // last 24 h (5-min intervals)
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
      tir: null,
      anomalies: [],
      latestReading: undefined,
      unacknowledgedCount: 0,
      handleAcknowledge,
    };
  }

  if (state.status === "not_found") {
    return { notFound: true as const, loading: false, error: null, patient: null, readings: [], tir: null, anomalies: [], latestReading: undefined, unacknowledgedCount: 0, handleAcknowledge };
  }

  if (state.status === "error") {
    return {
      notFound: false as const,
      loading: false as const,
      error: state.message,
      patient: null,
      readings: [],
      tir: null,
      anomalies: [],
      latestReading: undefined,
      unacknowledgedCount: 0,
      handleAcknowledge,
    };
  }

  const { patient, readings, tir, anomalies } = state;

  return {
    notFound: false as const,
    loading: false as const,
    error: null,
    patient,
    tir,
    readings,
    anomalies,
    latestReading: readings.length > 0 ? readings[0] : undefined, // ordered descending by backend
    unacknowledgedCount: anomalies.filter((a) => !a.is_acknowledged).length,
    handleAcknowledge,
  };
}
