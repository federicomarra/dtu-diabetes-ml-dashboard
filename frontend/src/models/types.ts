/**
 * Shared TypeScript interfaces for the diabetes dashboard.
 * MODEL layer — defines the data shapes used across the application.
 */

export interface Patient {
  id: number;
  external_id: string;
  name: string;
  age: number | string | null;
}

export interface GlucoseReading {
  id: number;
  patient_id: number;
  timestamp: string;
  glucose_mmoll: number;
  source: "simulated" | "dexcom" | "libre";
  status: "very_low" | "low" | "in_range" | "high" | "very_high";
}

export interface InsulinEvent {
  id: number;
  patient_id: number;
  timestamp: string;
  units: number;
  event_type: "bolus" | "basal";
  is_late: boolean;
  is_missed: boolean;
}

export interface MealEvent {
  id: number;
  patient_id: number;
  timestamp: string;
  carbs_grams: number;
  meal_type: "breakfast" | "lunch" | "dinner" | "snack" | null;
}

export interface ExerciseEvent {
  id: number;
  patient_id: number;
  timestamp: string;
  duration_minutes: number;
  intensity: "low" | "medium" | "high"; // TODO: check with Guido about these
}

export interface AnomalyDetection {
  id: number;
  patient_id: number;
  glucose_reading_id: number | null;
  anomaly_type: "missed_bolus" | "late_bolus" | "unusual_pattern";
  confidence: number;
  description: string | null;
  is_acknowledged: boolean;
  detected_at: string;
}

export interface TimeInRange {
  patient_id: number;
  total_readings: number;
  very_low_pct: number;
  low_pct: number;
  in_range_pct: number;
  high_pct: number;
  very_high_pct: number;
}

export interface PaginatedResponse<T> {
  patients: T[];
  total: number;
  page: number;
  pages: number;
}
