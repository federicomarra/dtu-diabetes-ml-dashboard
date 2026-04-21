/**
 * CONTROLLER — Patient Dashboard
 *
 * Owns all state and data for /patient.
 * Returns everything the view (page.tsx) needs; no logic in the page itself.
 *
 * TODO: replace demo data calls with real API calls from @/models/api once
 *       the backend is running:
 *   import { getGlucoseReadings, getTimeInRange, getAnomalies } from "@/models/api";
 */
"use client";

import { useMemo } from "react";
import {
  generateDemoReadings,
  DEMO_ANOMALIES,
} from "@/models/demoData";
import type { Patient, TimeInRange, AnomalyDetection } from "@/models/types";

// Demo patient — replace with session/auth lookup in production
const DEMO_PATIENT: Patient = {
  id: 1,
  external_id: "SIM_00001",
  name: "Demo Patient 000001",
  age: 34,
};

const DEMO_TIR: TimeInRange = {
  patient_id: 1,
  total_readings: 288,
  very_low_pct: 1.2,
  low_pct: 3.5,
  in_range_pct: 72.1,
  high_pct: 18.4,
  very_high_pct: 4.8,
};

export function usePatientController() {
  const readings = useMemo(() => generateDemoReadings(), []);
  const anomalies: AnomalyDetection[] = DEMO_ANOMALIES[DEMO_PATIENT.id] ?? [];

  return {
    patient: DEMO_PATIENT,
    readings,
    tir: DEMO_TIR,
    anomalies,
    latestReading: readings[readings.length - 1],
    unacknowledgedCount: anomalies.filter((a) => !a.is_acknowledged).length,
    handleAcknowledge: (id: number) => {
      console.log("Acknowledge anomaly:", id);
      // TODO: call acknowledgeAnomaly(id) from @/models/api
    },
  };
}
