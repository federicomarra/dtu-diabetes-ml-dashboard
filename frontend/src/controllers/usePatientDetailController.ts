/**
 * CONTROLLER — Doctor Patient Detail
 *
 * Owns all state and data for /doctor/[patient_id].
 * Accepts the external_id from the URL segment and resolves the patient.
 *
 * TODO: replace demo data with real API calls:
 *   import { getPatient, getGlucoseReadings, getTimeInRange, getAnomalies } from "@/models/api";
 */
"use client";

import { useState, useEffect } from "react";
import type { GlucoseReading } from "@/models/types";
import {
  getDemoPatientByExternalId,
  generateDemoReadings,
  DEMO_ANOMALIES,
} from "@/models/demoData";

export function usePatientDetailController(externalId: string) {
  const entry = getDemoPatientByExternalId(externalId);
  const [readings, setReadings] = useState<GlucoseReading[]>([]);

  useEffect(() => {
    const timer = setTimeout(() => {
      setReadings(generateDemoReadings());
    }, 10);
    return () => clearTimeout(timer);
  }, []);

  if (!entry) {
    return { notFound: true as const, patient: null, readings: [], tir: null, anomalies: [] };
  }

  const { patient, tir } = entry;
  const anomalies = DEMO_ANOMALIES[patient.id] ?? [];

  return {
    notFound: false as const,
    patient,
    tir,
    readings,
    anomalies,
    latestReading: readings.length > 0 ? readings[readings.length - 1] : undefined,
    unacknowledgedCount: anomalies.filter((a) => !a.is_acknowledged).length,
    handleAcknowledge: (id: number) => {
      console.log("Acknowledge anomaly:", id);
      // TODO: call acknowledgeAnomaly(id) from @/models/api
    },
  };
}
