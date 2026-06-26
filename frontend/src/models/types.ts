/**
 * Shared TypeScript interfaces for the diabetes dashboard.
 * MODEL layer — defines the data shapes used across the application.
 *
 * All field names match the snake_case JSON produced by the backend
 * (JsonNamingPolicy.SnakeCaseLower configured in Program.cs).
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

/** Maps to InsulinDto from DiabetesApi/Routes/Insulin.cs */
export interface InsulinEvent {
  id: number;
  patient_id: number;
  timestamp: string;
  units: number;
  event_type: "bolus" | "basal";
}

/** Maps to MealDto from DiabetesApi/Routes/Meal.cs */
export interface MealEvent {
  id: number;
  patient_id: number;
  timestamp: string;
  carbs: number;
  meal_type: "breakfast" | "lunch" | "dinner" | "snack" | null;
}

/** Maps to HistoryDto from DiabetesApi/Routes/History.cs */
export interface HistoryEntry {
  id: number;
  patient_id: number;
  timestamp: string;
  glucose: number | null;
  insulin: number | null;
  meal: number | null;
}

export interface AnomalyDetection {
  id: number;
  patient_id: number;
  glucose_reading_id: number | null;
  anomaly_type: "missed_bolus" | "late_bolus" | "unusual_pattern";
  confidence: number;
  description: string | null;
  is_acknowledged: boolean;
  detected_at?: string; // not present in backend; kept for forward-compat
}

export interface TimeInRange {
  patient_id: number;
  temporal_span_days: number;
  very_low_pct: number;
  low_pct: number;
  in_range_pct: number;
  high_pct: number;
  very_high_pct: number;
}

/** Maps to PaginatedPatientsResponse from DiabetesApi/Routes/Patient.cs */
export interface PaginatedResponse<T> {
  patients: T[];
  total: number;
  page: number;
  pages: number;
}

/** Maps to HbA1cResponse from DiabetesApi/Data/DTOs.cs */
export interface HbA1c {
  patient_id: number;
  percent: number;      // e.g. 6.5 (%)
  mmol_per_mol: number; // e.g. 48  (IFCC mmol/mol)
}

/** Maps to GmiResponse from DiabetesApi/Data/DTOs.cs */
export interface Gmi {
  patient_id: number;
  gmi: number; // e.g. 6.8 (%)
}
