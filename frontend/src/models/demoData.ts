/**
 * Demo / fixture data for development and the demo mode.
 * MODEL layer — all static data and data-generation utilities live here.
 *
 * Replace calls to these functions with real API calls (see models/api.ts)
 * when the backend is available.
 */
import type {
  Patient,
  GlucoseReading,
  TimeInRange,
  AnomalyDetection,
} from "@/models/types";
import {
  VERY_LOW_THRESHOLD,
  LOW_THRESHOLD,
  HIGH_THRESHOLD,
  VERY_HIGH_THRESHOLD,
  GLUCOSE_CLAMP_MIN,
  GLUCOSE_CLAMP_MAX,
} from "@/models/glucoseConfig";

// ─── Glucose reading generator ────────────────────────────

export function generateDemoReadings(): GlucoseReading[] {
  const readings: GlucoseReading[] = [];
  const now = new Date();
  let glucose = 6.1; // mmol/L

  for (let i = 288; i >= 0; i--) {
    const timestamp = new Date(now.getTime() - i * 5 * 60 * 1000);
    const hour = timestamp.getHours();

    // Simulate meal spikes
    const mealEffect =
      (hour >= 7 && hour <= 9) ||
        (hour >= 12 && hour <= 14) ||
        (hour >= 18 && hour <= 20)
        ? Math.random() * 0.17 // ~3 mg/dL in mmol/L
        : 0;

    glucose +=
      (6.1 - glucose) * 0.02 + (Math.random() - 0.5) * 0.33 + mealEffect;
    glucose = Math.max(GLUCOSE_CLAMP_MIN, Math.min(GLUCOSE_CLAMP_MAX, glucose));

    const status: GlucoseReading["status"] =
      glucose < VERY_LOW_THRESHOLD
        ? "very_low"
        : glucose < LOW_THRESHOLD
          ? "low"
          : glucose <= HIGH_THRESHOLD
            ? "in_range"
            : glucose <= VERY_HIGH_THRESHOLD
              ? "high"
              : "very_high";

    readings.push({
      id: i,
      patient_id: 1,
      timestamp: timestamp.toISOString(),
      glucose_mmoll: Math.round(glucose * 10) / 10,
      source: "simulated",
      status,
    });
  }
  return readings;
}

// ─── Patient list ─────────────────────────────────────────

export const DEMO_PATIENTS: Array<{
  patient: Patient;
  latestReading: GlucoseReading;
  tir: TimeInRange;
  anomalyCount: number;
}> = [
    {
      patient: { id: 1, external_id: "DEMO_000001", name: "Alice Johnson", age: 34 },
      latestReading: {
        id: 1, patient_id: 1, timestamp: new Date().toISOString(),
        glucose_mmoll: 8.1, source: "simulated", status: "in_range",
      },
      tir: {
        patient_id: 1, temporal_span_days: 7,
        very_low_pct: 1.2, low_pct: 3.5, in_range_pct: 72.1,
        high_pct: 18.4, very_high_pct: 4.8,
      },
      anomalyCount: 2,
    },
    {
      patient: { id: 2, external_id: "DEMO_000002", name: "Bob Smith", age: 39 },
      latestReading: {
        id: 2, patient_id: 2, timestamp: new Date().toISOString(),
        glucose_mmoll: 5.3, source: "simulated", status: "in_range",
      },
      tir: {
        patient_id: 2, temporal_span_days: 14,
        very_low_pct: 0.5, low_pct: 2.1, in_range_pct: 85.3,
        high_pct: 10.2, very_high_pct: 1.9,
      },
      anomalyCount: 0,
    },
    {
      patient: { id: 3, external_id: "DEMO_000003", name: "Clara Andersen", age: 26 },
      latestReading: {
        id: 3, patient_id: 3, timestamp: new Date().toISOString(),
        glucose_mmoll: 14.9, source: "simulated", status: "very_high",
      },
      tir: {
        patient_id: 3, temporal_span_days: 30,
        very_low_pct: 3.1, low_pct: 5.2, in_range_pct: 55.8,
        high_pct: 22.4, very_high_pct: 13.5,
      },
      anomalyCount: 5,
    },
    {
      patient: { id: 4, external_id: "DEMO_000004", name: "David Nielsen", age: 49 },
      latestReading: {
        id: 4, patient_id: 4, timestamp: new Date().toISOString(),
        glucose_mmoll: 3.4, source: "simulated", status: "low",
      },
      tir: {
        patient_id: 4, temporal_span_days: 170,
        very_low_pct: 4.5, low_pct: 8.3, in_range_pct: 64.7,
        high_pct: 16.1, very_high_pct: 6.4,
      },
      anomalyCount: 3,
    },
  ];

// ─── Anomalies ────────────────────────────────────────────

/** Per-patient demo anomalies (keyed by patient.id). */
export const DEMO_ANOMALIES: Record<number, AnomalyDetection[]> = {
  1: [
    {
      id: 1, patient_id: 1, glucose_reading_id: 42,
      anomaly_type: "missed_bolus", confidence: 0.85,
      description: "Glucose at 14.7 mmol/L with no bolus in preceding 30 min",
      is_acknowledged: false,
      detected_at: new Date(Date.now() - 2 * 3600 * 1000).toISOString(),
    },
    {
      id: 2, patient_id: 1, glucose_reading_id: 100,
      anomaly_type: "late_bolus", confidence: 0.62,
      description: "Bolus administered 45 min after meal start",
      is_acknowledged: false,
      detected_at: new Date(Date.now() - 6 * 3600 * 1000).toISOString(),
    },
  ],
  2: [],
  3: [
    {
      id: 3, patient_id: 3, glucose_reading_id: null,
      anomaly_type: "missed_bolus", confidence: 0.91,
      description: "Sustained hyperglycaemia — no bolus recorded for 90 min",
      is_acknowledged: false,
      detected_at: new Date(Date.now() - 1 * 3600 * 1000).toISOString(),
    },
    {
      id: 4, patient_id: 3, glucose_reading_id: null,
      anomaly_type: "unusual_pattern", confidence: 0.76,
      description: "Unusual glucose pattern detected overnight",
      is_acknowledged: false,
      detected_at: new Date(Date.now() - 5 * 3600 * 1000).toISOString(),
    },
  ],
  4: [
    {
      id: 5, patient_id: 4, glucose_reading_id: 201,
      anomaly_type: "late_bolus", confidence: 0.78,
      description: "Bolus administered 35 min after meal start",
      is_acknowledged: true,
      detected_at: new Date(Date.now() - 8 * 3600 * 1000).toISOString(),
    },
  ],
};

// ─── Helpers ──────────────────────────────────────────────

/** Returns the DEMO_PATIENTS entry matching the given external_id, or undefined. */
export function getDemoPatientByExternalId(externalId: string) {
  return DEMO_PATIENTS.find((p) => p.patient.external_id === externalId);
}
