/**
 * Typed API client for the diabetes dashboard backend.
 * MODEL layer — raw data access, all HTTP calls live here.
 */
import axios from "axios";
import type {
  Patient,
  GlucoseReading,
  AnomalyDetection,
  TimeInRange,
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
  const { data } = await api.get("/patients/", {
    params: { page, per_page: perPage },
  });
  return data;
}

export async function getPatient(patientId: number): Promise<Patient> {
  const { data } = await api.get(`/patients/${patientId}`);
  return data;
}

export async function createPatient(
  patient: Pick<Patient, "external_id" | "name">
): Promise<Patient> {
  const { data } = await api.post("/patients/", patient);
  return data;
}

// ─── Glucose ─────────────────────────────────────────────

export async function getGlucoseReadings(
  patientId: number,
  params?: { start?: string; end?: string; limit?: number }
): Promise<{ patient_id: number; readings: GlucoseReading[]; count: number }> {
  const { data } = await api.get(`/glucose/${patientId}`, { params });
  return data;
}

export async function getLatestReading(
  patientId: number
): Promise<GlucoseReading> {
  const { data } = await api.get(`/glucose/${patientId}/latest`);
  return data;
}

export async function getTimeInRange(
  patientId: number,
  params?: { start?: string; end?: string }
): Promise<TimeInRange> {
  const { data } = await api.get(`/glucose/${patientId}/tir`, { params });
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
  const { data } = await api.post(`/anomalies/${anomalyId}/acknowledge`);
  return data;
}

// ─── Health ──────────────────────────────────────────────

export async function healthCheck(): Promise<{ status: string }> {
  const { data } = await api.get("/health");
  return data;
}
