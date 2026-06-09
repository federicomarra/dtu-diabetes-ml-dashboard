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

import { useState, useEffect } from "react";
import {
  generateDemoReadings,
  generateMultiWeekReadings,
  DEMO_ANOMALIES,
} from "@/models/demoData";
import type { Patient, TimeInRange, AnomalyDetection, GlucoseReading } from "@/models/types";

// Demo patient — replace with session/auth lookup in production
const DEMO_PATIENT: Patient = {
  id: 1,
  external_id: "SIM_00001",
  name: "Demo Patient 000001",
  age: 34,
};

const DEMO_TIR: TimeInRange = {
  patient_id: 1,
  temporal_span_days: 7,
  very_low_pct: 1.2,
  low_pct: 3.5,
  in_range_pct: 72.1,
  high_pct: 18.4,
  very_high_pct: 4.8,
};

const DEMO_AVERAGE: number = 6.8;

export function usePatientController() {
  const [readings, setReadings] = useState<GlucoseReading[]>([]);
  const [multiWeekReadings, setMultiWeekReadings] = useState<GlucoseReading[]>([]);
  const anomalies: AnomalyDetection[] = DEMO_ANOMALIES[DEMO_PATIENT.id] ?? [];

  useEffect(() => {
    const timer = setTimeout(() => {
      setReadings(generateDemoReadings());
      setMultiWeekReadings(generateMultiWeekReadings(4)); // last 4 weeks
    }, 0);
    return () => clearTimeout(timer);
  }, []);

  return {
    patient: DEMO_PATIENT,
    readings,
    multiWeekReadings,
    tir: DEMO_TIR,
    anomalies,
    averageGlucose: DEMO_AVERAGE,
    latestReading: readings.length > 0 ? readings[readings.length - 1] : undefined,
    unacknowledgedCount: anomalies.filter((a) => !a.is_acknowledged).length,
    handleAcknowledge: (id: number) => {
      console.log("Acknowledge anomaly:", id);
      // TODO: call acknowledgeAnomaly(id) from @/models/api
    },
  };
}

