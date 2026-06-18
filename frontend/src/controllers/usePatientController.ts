/**
 * CONTROLLER — Patient Dashboard
 *
 * Owns all state and data for /patient.
 * Resolves the hardcoded patient SIM_000001, then loads glucose readings,
 * TIR, and anomalies from the backend.
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
  getAverageReading,
} from "@/models/api";
import { useTimeRange } from "@/controllers/TimeRangeContext";
import { useGlucoseRanges } from "@/controllers/GlucoseRangesContext";

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | {
      status: "ready";
      patient: Patient;
      readings: GlucoseReading[];
      multiWeekReadings: GlucoseReading[];
      tir: TimeInRange | null;
      anomalies: AnomalyDetection[];
      averageGlucose: number | null;
    };

export function usePatientController() {
  const [state, setState] = useState<State>({ status: "loading" });
  const { timeRange } = useTimeRange();
  const { ranges: glucoseRanges } = useGlucoseRanges();

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        setState({ status: "loading" });

        // Resolve patient SIM_000001
        let patient;
        try {
          patient = await getPatientByExternalId("SIM_000001");
        } catch (err: unknown) {
          if (cancelled) return;
          setState({
            status: "error",
            message: err instanceof Error ? err.message : "Failed to load patient",
          });
          return;
        }

        if (cancelled) return;

        // Fetch data in parallel
        const [readingsResult, tirResult, anomaliesResult, averageResult] =
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
          tir: tirResult.status === "fulfilled" ? tirResult.value : null,
          anomalies:
            anomaliesResult.status === "fulfilled"
              ? anomaliesResult.value.anomalies
              : [],
          averageGlucose:
            averageResult.status === "fulfilled" ? averageResult.value : null,
        });
      } catch (err) {
        if (!cancelled) {
          setState({
            status: "error",
            message: err instanceof Error ? err.message : "Failed to load data",
          });
        }
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [timeRange, glucoseRanges]);

  const handleAcknowledge = useCallback(async (anomalyId: number) => {
    try {
      await acknowledgeAnomaly(anomalyId);
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
  }, []);

  if (state.status === "loading") {
    return {
      loading: true as const,
      error: null,
      patient: null,
      readings: [],
      multiWeekReadings: [],
      tir: null,
      anomalies: [],
      averageGlucose: null,
      latestReading: undefined,
      unacknowledgedCount: 0,
      handleAcknowledge,
    };
  }

  if (state.status === "error") {
    return {
      loading: false as const,
      error: state.message,
      patient: null,
      readings: [],
      multiWeekReadings: [],
      tir: null,
      anomalies: [],
      averageGlucose: null,
      latestReading: undefined,
      unacknowledgedCount: 0,
      handleAcknowledge,
    };
  }

  const { patient, readings, multiWeekReadings, tir, anomalies, averageGlucose } = state;

  return {
    loading: false as const,
    error: null,
    patient,
    tir,
    readings,
    multiWeekReadings,
    anomalies,
    averageGlucose,
    latestReading: readings.length > 0 ? readings[0] : undefined,
    unacknowledgedCount: anomalies.filter((a) => !a.is_acknowledged).length,
    handleAcknowledge,
  };
}
