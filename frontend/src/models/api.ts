/**
 * Typed API client for the diabetes dashboard backend.
 * MODEL layer — raw data access, all HTTP calls live here.
 *
 * Route mapping (from backend/DiabetesApi/Routes/):
 *   GET  api/patient/list              → getPatients()
 *   GET  api/patient/{id}              → getPatient()
 *   POST api/patient/create            → createPatient()
 *   GET  api/glucose?id={id}           → getGlucoseReadings()
 *   GET  api/glucose/latest?id={id}    → getLatestReading()
 *   GET  api/glucose/tir?id={id}       → getTimeInRange()
 *   GET  api/glucose/average?id={id}   → getAverageReading()
 *   GET  api/glucose/hba1c?id={id}     → getHbA1c()
 *   GET  api/glucose/gmi?id={id}       → getGmi()
 *   GET  api/anomaly/{id}              → getAnomalies()
 *   POST api/anomaly/{id}/acknowledge  → acknowledgeAnomaly()
 *   GET  api/insulin/{id}              → getInsulins()
 *   GET  api/meal/{id}                 → getMeals()
 *   GET  api/history/{id}              → getHistory()
 *   GET  api/health                    → healthCheck()
 */
import axios from "axios";
import type {
  Patient,
  GlucoseReading,
  AnomalyDetection,
  TimeInRange,
  HbA1c,
  Gmi,
  ScatterplotData,
  InsulinEvent,
  MealEvent,
  HistoryEntry,
  PaginatedResponse,
} from "@/models/types";

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api",
  timeout: 30000,
  headers: { "Content-Type": "application/json" },
});

// ─── Patients ────────────────────────────────────────────

export async function getPatients(
  page = 1,
  perPage = 20
): Promise<PaginatedResponse<Patient>> {
  const { data } = await api.get("/patient/list", {
    params: { page, perPage },
  });
  return data;
}

export async function getPatient(patientId: number): Promise<Patient> {
  const { data } = await api.get(`/patient/${patientId}`);
  return data;
}

export async function getPatientByExternalId(externalId: string): Promise<Patient> {
  const { data } = await api.get(`/patient/by-external/${encodeURIComponent(externalId)}`);
  return data;
}

export async function createPatient(
  patient: Pick<Patient, "external_id" | "name">
): Promise<Patient> {
  const { data } = await api.post("/patient/create", patient);
  return data;
}

// ─── Glucose ─────────────────────────────────────────────

export async function getGlucoseReadings(
  patientId: number,
  params?: { start?: string; end?: string; last?: string }
): Promise<{ patient_id: number; readings: GlucoseReading[]; count: number }> {
  const { data } = await api.get("/glucose", { params: { id: patientId, ...params } });
  return data;
}

export async function getLatestReading(
  patientId: number
): Promise<GlucoseReading> {
  const { data } = await api.get("/glucose/latest", { params: { id: patientId } });
  return data;
}

export async function getTimeInRange(
  patientId: number,
  params?: { start?: string; end?: string; last?: string; VeryLow?: number; Low?: number; High?: number; VeryHigh?: number }
): Promise<TimeInRange> {
  const { data } = await api.get("/glucose/tir", { params: { id: patientId, ...params } });
  return data;
}

export async function getAverageReading(
  patientId: number,
  params?: { start?: string; end?: string; last?: string }
): Promise<number> {
  const { data } = await api.get("/glucose/average", { params: { id: patientId, ...params } });
  return data;
}

export async function getHbA1c(
  patientId: number,
  params?: { start?: string; end?: string; last?: string }
): Promise<HbA1c> {
  const { data } = await api.get("/glucose/hba1c", { params: { id: patientId, ...params } });
  return data;
}

export async function getGmi(
  patientId: number,
  params?: { start?: string; end?: string; last?: string }
): Promise<Gmi> {
  const { data } = await api.get("/glucose/gmi", { params: { id: patientId, ...params } });
  return data;
}

export async function getScatterplot(
  patientId: number,
  params?: { start?: string; end?: string; last?: string }
): Promise<ScatterplotData> {
  const { data } = await api.get("/glucose/scatterplot", { params: { id: patientId, ...params } });
  return data;
}

// ─── Anomalies ───────────────────────────────────────────

export async function getAnomalies(
  patientId: number,
  params?: { acknowledged?: boolean; limit?: number }
): Promise<{ patient_id: number; anomalies: AnomalyDetection[]; count: number }> {
  const { data } = await api.get(`/anomalies/${patientId}`, { params });
  return data;
}

export async function acknowledgeAnomaly(
  anomalyId: number
): Promise<AnomalyDetection> {
  const { data } = await api.post(`/anomaly/${anomalyId}/acknowledge`);
  return data;
}

// ─── Insulin ─────────────────────────────────────────────

export async function getInsulins(
  patientId: number,
  params?: { start?: string; end?: string; last?: string }
): Promise<{ patient_id: number; insulins: InsulinEvent[]; count: number }> {
  const { data } = await api.get(`/insulin/${patientId}`, { params });
  return data;
}

// ─── Meals ───────────────────────────────────────────────

export async function getMeals(
  patientId: number,
  params?: { start?: string; end?: string; last?: string }
): Promise<{ patient_id: number; meals: MealEvent[]; count: number }> {
  const { data } = await api.get(`/meal/${patientId}`, { params });
  return data;
}

// ─── History ─────────────────────────────────────────────

export async function getHistory(
  patientId: number,
  limit = 100
): Promise<{ patient_id: number; histories: HistoryEntry[]; count: number }> {
  const { data } = await api.get(`/history/${patientId}`, {
    params: { limit },
  });
  return data;
}

// ─── Health check ────────────────────────────────────────

export async function healthCheck(): Promise<{ status: string }> {
  const { data } = await api.get("/health");
  return data;
}
