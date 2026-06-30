/**
 * CONTROLLER — Doctor Patient Detail
 *
 * Owns all state and data for /doctor/[patient_id].
 * Accepts the external_id from the URL segment, resolves the patient,
 * then loads glucose readings, TIR, and anomalies from the backend.
 *
 * API calls (see models/api.ts):
 *   GET api/patient/by-external/{externalId} → resolve external_id → patient
 *   GET api/glucose?id={patientId}           → glucose readings
 *   GET api/glucose/tir?id={patientId}       → time-in-range stats
 *   GET api/glucose/average?id={patientId}   → average glucose
 *   GET api/glucose/hba1c?id={patientId}     → estimated HbA1c
 *   GET api/glucose/gmi?id={patientId}       → GMI
 *   GET api/glucose/scatterplot?id={patientId} → daily scatterplot averages
 *   GET api/anomaly/{patientId}              → anomaly list
 *   POST api/anomaly/{anomalyId}/acknowledge → acknowledge anomaly
 */
"use client";

import { useState, useEffect, useCallback } from "react";
import type { Patient, GlucoseReading, TimeInRange, AnomalyDetection, HbA1c, Gmi, ScatterplotData } from "@/models/types";
import {
  getPatientByExternalId,
  getGlucoseReadings,
  getTimeInRange,
  getAnomalies,
  acknowledgeAnomaly,
  getAverageReading,
  getHbA1c,
  getGmi,
  getScatterplot,
} from "@/models/api";
import { useTimeRange } from "@/controllers/TimeRangeContext";
import { useGlucoseRanges } from "@/controllers/GlucoseRangesContext";

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
      averageGlucose: number | null;
      hba1c: HbA1c | null;
      gmi: Gmi | null;
      scatterplotData: ScatterplotData | null;
    };

export function usePatientDetailController(externalId: string) {
  const [state, setState] = useState<State>({ status: "loading" });
  const { timeRange } = useTimeRange();
  const { ranges: glucoseRanges } = useGlucoseRanges();
  const [refreshKey, setRefreshKey] = useState(0);

  const refresh = useCallback(() => {
    setRefreshKey((prev) => prev + 1);
  }, []);

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
        const [readingsResult, tirResult, anomaliesResult, averageResult, hba1cResult, gmiResult, scatterplotResult] =
          await Promise.allSettled([
            getGlucoseReadings(patient.id, timeRange),
            getTimeInRange(patient.id, {
              ...timeRange,
              VeryLow: glucoseRanges.veryLow,
              Low: glucoseRanges.low,
              High: glucoseRanges.high,
              VeryHigh: glucoseRanges.veryHigh,
            }),
            getAnomalies(patient.id, { limit: 50 }),
            getAverageReading(patient.id, timeRange),
            getHbA1c(patient.id, timeRange),
            getGmi(patient.id, timeRange),
            getScatterplot(patient.id, timeRange),
          ]);

        if (cancelled) return;

        const fetchedReadings =
          readingsResult.status === "fulfilled"
            ? readingsResult.value.readings
            : [];

        setState({
          status: "ready",
          patient,
          readings: fetchedReadings,
          multiWeekReadings: fetchedReadings,
          tir:
            tirResult.status === "fulfilled" ? tirResult.value : null,
          anomalies:
            anomaliesResult.status === "fulfilled"
              ? anomaliesResult.value.anomalies
              : [],
          averageGlucose:
            averageResult.status === "fulfilled" ? averageResult.value : null,
          hba1c: hba1cResult.status === "fulfilled" ? hba1cResult.value : null,
          gmi: gmiResult.status === "fulfilled" ? gmiResult.value : null,
          scatterplotData: scatterplotResult.status === "fulfilled" ? scatterplotResult.value : null,
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
  }, [externalId, timeRange, glucoseRanges, refreshKey]);

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
      averageGlucose: null,
      hba1c: null,
      gmi: null,
      scatterplotData: null,
      latestReading: undefined,
      unacknowledgedCount: 0,
      handleAcknowledge,
      refresh,
    };
  }

  if (state.status === "not_found") {
    return { notFound: true as const, loading: false, error: null, patient: null, readings: [], multiWeekReadings: [] as GlucoseReading[], tir: null, anomalies: [], averageGlucose: null, hba1c: null, gmi: null, scatterplotData: null, latestReading: undefined, unacknowledgedCount: 0, handleAcknowledge, refresh };
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
      averageGlucose: null,
      hba1c: null,
      gmi: null,
      scatterplotData: null,
      latestReading: undefined,
      unacknowledgedCount: 0,
      handleAcknowledge,
      refresh,
    };
  }

  const { patient, readings, multiWeekReadings, tir, anomalies, averageGlucose, hba1c, gmi, scatterplotData } = state;

  return {
    notFound: false as const,
    loading: false as const,
    error: null,
    patient,
    tir,
    readings,
    multiWeekReadings,
    anomalies,
    averageGlucose,
    hba1c,
    gmi,
    scatterplotData,
    latestReading: readings.length > 0 ? readings[0] : undefined, // ordered descending by backend
    unacknowledgedCount: anomalies.filter((a) => !a.is_acknowledged).length,
    handleAcknowledge,
    refresh,
  };
}
