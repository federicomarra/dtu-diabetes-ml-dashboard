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
  HbA1c,
  Gmi,
  ScatterplotData,
  InsulinEvent,
  MealEvent,
  PaginatedResponse,
} from "@/models/types";
import {
  getDemoPatients,
  getDemoPatient,
  getDemoPatientByExternalId,
  createDemoPatient,
  getDemoGlucoseReadings,
  getDemoLatestReading,
  getDemoTimeInRange,
  getDemoAverageReading,
  getDemoHbA1c,
  getDemoGmi,
  getDemoScatterplot,
  getDemoAnomalies,
  runDemoDetection,
  acknowledgeDemoAnomaly,
  getDemoInsulins,
  getDemoMeals,
  simulateUploadCsv,
  simulateUploadGlookoZip,
  simulateUploadParquet,
} from "@/models/demoData";

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api",
  timeout: 30000,
  headers: { "Content-Type": "application/json" },
});

// ─── Health check caching & Demo Mode Resolver ─────────────

let isHealthyCache: boolean | null = null;
let healthCheckPromise: Promise<boolean> | null = null;

export async function checkIsHealthy(): Promise<boolean> {
  if (isHealthyCache !== null) return isHealthyCache;
  if (healthCheckPromise) return healthCheckPromise;

  healthCheckPromise = (async () => {
    try {
      const response = await api.get("/health", { timeout: 3000 });
      const backendStatus = response.data?.components?.backend?.status?.toLowerCase();
      const isHealthy = backendStatus === "healthy";
      isHealthyCache = isHealthy;
      return isHealthy;
    } catch (e) {
      console.warn("Backend offline or unreachable, using fallback demo data.", e);
      isHealthyCache = false;
      return false;
    } finally {
      healthCheckPromise = null;
    }
  })();

  return healthCheckPromise;
}

// Pre-emptively probe if running in the browser
if (typeof window !== "undefined") {
  checkIsHealthy();
}

export function isDemoModeActive(): boolean {
  return isHealthyCache === false;
}

async function shouldRunDemo(): Promise<boolean> {
  const healthy = await checkIsHealthy();
  return !healthy;
}

// ─── Patients ────────────────────────────────────────────

export async function getPatients(
  page = 1,
  perPage = 20,
  sortBy?: string,
  sortDir?: string,
  timeRange?: { last?: string; start?: string; end?: string },
  ranges?: { low?: number; high?: number }
): Promise<PaginatedResponse<Patient>> {
  if (await shouldRunDemo()) {
    return getDemoPatients(page, perPage, sortBy, sortDir, timeRange, ranges);
  }
  const { data } = await api.get("/patient/list", {
    params: {
      page,
      perPage,
      sortBy,
      sortDir,
      start: timeRange?.start,
      end: timeRange?.end,
      last: timeRange?.last,
      low: ranges?.low,
      high: ranges?.high,
    },
  });
  return data;
}

export async function getPatient(patientId: number): Promise<Patient> {
  if (await shouldRunDemo()) {
    return getDemoPatient(patientId);
  }
  const { data } = await api.get("/patient", { params: { id: patientId } });
  return data;
}

export async function getPatientByExternalId(externalId: string): Promise<Patient> {
  if (await shouldRunDemo()) {
    return getDemoPatientByExternalId(externalId);
  }
  const { data } = await api.get("/patient", { params: { ext_id: externalId } });
  return data;
}

export async function createPatient(
  patient: { external_id: string; name: string; date_of_birth?: string }
): Promise<Patient> {
  if (await shouldRunDemo()) {
    return createDemoPatient(patient);
  }
  const { data } = await api.post("/patient/create", patient);
  return data;
}

export async function uploadCsv(
  patientId: number,
  file: File
): Promise<{ message: string; glucose_count: number; meal_count: number; insulin_count: number; date_from: string | null; date_to: string | null }> {
  if (await shouldRunDemo()) {
    return simulateUploadCsv(patientId, file);
  }
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await api.post("/patient/upload-libre-csv", formData, {
    params: { id: patientId },
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 120000,
  });
  return data;
}

export async function uploadGlookoZip(
  patientId: number,
  file: File
): Promise<{ message: string; glucose_count: number; meal_count: number; insulin_count: number; date_from: string | null; date_to: string | null }> {
  if (await shouldRunDemo()) {
    return simulateUploadGlookoZip(patientId, file);
  }
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await api.post("/patient/upload-glooko-zip", formData, {
    params: { id: patientId },
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 120000,
  });
  return data;
}

export async function uploadParquet(
  file: File
): Promise<{ message: string; patients_count: number; glucose_count: number; meal_count: number; insulin_count: number }> {
  if (await shouldRunDemo()) {
    return simulateUploadParquet(file);
  }
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await api.post("/doctor/upload-parquet", formData, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 300000,
  });
  return data;
}

// ─── Glucose ─────────────────────────────────────────────

export async function getGlucoseReadings(
  patientId: number,
  params?: { start?: string; end?: string; last?: string }
): Promise<{ patient_id: number; readings: GlucoseReading[]; count: number }> {
  if (await shouldRunDemo()) {
    return getDemoGlucoseReadings(patientId, params);
  }
  const { data } = await api.get("/glucose", { params: { id: patientId, ...params } });
  return data;
}

export async function getLatestReading(
  patientId: number
): Promise<GlucoseReading> {
  if (await shouldRunDemo()) {
    return getDemoLatestReading(patientId);
  }
  const { data } = await api.get("/glucose/latest", { params: { id: patientId } });
  return data;
}

export async function getTimeInRange(
  patientId: number,
  params?: { start?: string; end?: string; last?: string; VeryLow?: number; Low?: number; High?: number; VeryHigh?: number }
): Promise<TimeInRange> {
  if (await shouldRunDemo()) {
    return getDemoTimeInRange(patientId, params);
  }
  const { data } = await api.get("/glucose/tir", { params: { id: patientId, ...params } });
  return data;
}

export async function getAverageReading(
  patientId: number,
  params?: { start?: string; end?: string; last?: string }
): Promise<number> {
  if (await shouldRunDemo()) {
    return getDemoAverageReading(patientId, params);
  }
  const { data } = await api.get("/glucose/average", { params: { id: patientId, ...params } });
  return data;
}

export async function getHbA1c(
  patientId: number,
  params?: { start?: string; end?: string; last?: string }
): Promise<HbA1c> {
  if (await shouldRunDemo()) {
    return getDemoHbA1c(patientId, params);
  }
  const { data } = await api.get("/glucose/hba1c", { params: { id: patientId, ...params } });
  return data;
}

export async function getGmi(
  patientId: number,
  params?: { start?: string; end?: string; last?: string }
): Promise<Gmi> {
  if (await shouldRunDemo()) {
    return getDemoGmi(patientId, params);
  }
  const { data } = await api.get("/glucose/gmi", { params: { id: patientId, ...params } });
  return data;
}

export async function getScatterplot(
  patientId: number,
  params?: { start?: string; end?: string; last?: string }
): Promise<ScatterplotData> {
  if (await shouldRunDemo()) {
    return getDemoScatterplot(patientId, params);
  }
  const { data } = await api.get("/glucose/scatterplot", { params: { id: patientId, ...params } });
  return data;
}

// ─── Anomalies ───────────────────────────────────────────

export async function getAnomalies(
  patientId: number,
  params?: { start?: string; end?: string; last?: string }
): Promise<{ patient_id: number; anomalies: AnomalyDetection[]; count: number }> {
  if (await shouldRunDemo()) {
    return getDemoAnomalies(patientId, params);
  }
  const { data } = await api.get(`/anomaly`, {
    params: {
      id: patientId,
      start: params?.start,
      end: params?.end,
      last: params?.last,
    },
  });
  return data;
}

export async function runDetection(
  patientId: number,
  params?: { start?: string; end?: string; last?: string }
): Promise<{ patient_id: number; anomalies: AnomalyDetection[]; count: number }> {
  if (await shouldRunDemo()) {
    return runDemoDetection(patientId, params);
  }
  const { data } = await api.post(`/anomaly/detect`, null, { params: { id: patientId, ...params } });
  return data;
}

export async function acknowledgeAnomaly(
  patientId: number,
  anomalyId: number
): Promise<AnomalyDetection> {
  if (await shouldRunDemo()) {
    return acknowledgeDemoAnomaly(patientId, anomalyId);
  }
  const { data } = await api.post(`/anomaly/acknowledge`, null, { params: { patientId: patientId, anomalyId } });
  return data;
}

// ─── Insulin ─────────────────────────────────────────────

export async function getInsulins(
  patientId: number,
  params?: { start?: string; end?: string; last?: string }
): Promise<{ patient_id: number; insulins: InsulinEvent[]; count: number }> {
  if (await shouldRunDemo()) {
    return getDemoInsulins(patientId, params);
  }
  const { data } = await api.get(`/insulin`, { params: { id: patientId, ...params } });
  return data;
}

// ─── Meals ───────────────────────────────────────────────

export async function getMeals(
  patientId: number,
  params?: { start?: string; end?: string; last?: string }
): Promise<{ patient_id: number; meals: MealEvent[]; count: number }> {
  if (await shouldRunDemo()) {
    return getDemoMeals(patientId, params);
  }
  const { data } = await api.get(`/meal`, { params: { id: patientId, ...params } });
  return data;
}

// ─── Health check ────────────────────────────────────────

export async function healthCheck(): Promise<{
  status: string;
  components?: {
    backend?: { status: string };
    database?: { status: string };
    ml?: { detector?: string; device?: string; status: string };
  };
}> {
  const { data } = await api.get("/health");
  return data;
}
