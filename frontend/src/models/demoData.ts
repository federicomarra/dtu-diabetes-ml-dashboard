/**
 * Demo / fixture data for development and the demo mode.
 * MODEL layer — all static data and data-generation utilities live here.
 */
import type {
  Patient,
  GlucoseReading,
  TimeInRange,
  AnomalyDetection,
  InsulinEvent,
  MealEvent,
  ScatterplotData,
  DailyGlucosePoint,
  HbA1c,
  Gmi,
  PaginatedResponse,
} from "@/models/types";
import {
  VERY_LOW_THRESHOLD,
  LOW_THRESHOLD,
  HIGH_THRESHOLD,
  VERY_HIGH_THRESHOLD,
  GLUCOSE_CLAMP_MIN,
  GLUCOSE_CLAMP_MAX,
} from "@/models/glucoseConfig";

// ─── Constants for Seed Data ──────────────────────────────

export const DEMO_PATIENTS_SEEDS = [
  { id: 1, external_id: "DEMO_000001", name: "Alice Johnson", age: 34 },
  { id: 2, external_id: "DEMO_000002", name: "Bob Smith", age: 39 },
  { id: 3, external_id: "DEMO_000003", name: "Clara Andersen", age: 26 },
  { id: 4, external_id: "DEMO_000004", name: "David Nielsen", age: 49 },
  { id: 5, external_id: "DEMO_000005", name: "Eva Pedersen", age: 31 },
];

const SEED_ANOMALIES: Record<number, Omit<AnomalyDetection, "patient_id">[]> = {
  1: [
    {
      id: 1, glucose_reading_id: 42,
      anomaly_type: "missed_bolus", confidence: 0.85,
      description: "Glucose at 14.7 mmol/L with no bolus in preceding 30 min",
      is_acknowledged: false,
      detected_at: new Date(Date.now() - 2 * 3600 * 1000).toISOString(),
    },
    {
      id: 2, glucose_reading_id: 100,
      anomaly_type: "late_bolus", confidence: 0.62,
      description: "Bolus administered 45 min after meal start",
      is_acknowledged: false,
      detected_at: new Date(Date.now() - 6 * 3600 * 1000).toISOString(),
    },
  ],
  2: [],
  3: [
    {
      id: 3, glucose_reading_id: null,
      anomaly_type: "missed_bolus", confidence: 0.91,
      description: "Sustained hyperglycaemia — no bolus recorded for 90 min",
      is_acknowledged: false,
      detected_at: new Date(Date.now() - 1 * 3600 * 1000).toISOString(),
    },
    {
      id: 4, glucose_reading_id: null,
      anomaly_type: "unusual_pattern", confidence: 0.76,
      description: "Unusual glucose pattern detected overnight",
      is_acknowledged: false,
      detected_at: new Date(Date.now() - 5 * 3600 * 1000).toISOString(),
    },
  ],
  4: [
    {
      id: 5, glucose_reading_id: 201,
      anomaly_type: "late_bolus", confidence: 0.78,
      description: "Bolus administered 35 min after meal start",
      is_acknowledged: true,
      detected_at: new Date(Date.now() - 8 * 3600 * 1000).toISOString(),
    },
  ],
  5: [
    {
      id: 6, glucose_reading_id: null,
      anomaly_type: "missed_bolus", confidence: 0.72,
      description: "Glucose at 12.1 mmol/L with no bolus in preceding 30 min",
      is_acknowledged: false,
      detected_at: new Date(Date.now() - 4 * 3600 * 1000).toISOString(),
    },
  ],
};

// ─── In-Memory Mutable Database State ─────────────────────

let stateInitialized = false;
let patientsList: Patient[] = [];
const glucoseReadingsMap: Record<number, GlucoseReading[]> = {};
const insulinEventsMap: Record<number, InsulinEvent[]> = {};
const mealEventsMap: Record<number, MealEvent[]> = {};
const anomaliesMap: Record<number, AnomalyDetection[]> = {};

// ─── Helper: Time Filtering ──────────────────────────────

function getSpanDays(last?: string): number {
  if (!last) return 14;
  const match = last.match(/^(\d+)([hdwmy])$/);
  if (!match) return 14;
  const value = parseInt(match[1], 10);
  const unit = match[2];
  switch (unit) {
    case "h": return value / 24;
    case "d": return value;
    case "w": return value * 7;
    case "m": return value * 30;
    case "y": return value * 365;
    default: return value;
  }
}

function filterByTimeParams<T extends { timestamp?: string; detected_at?: string }>(
  items: T[],
  params?: { start?: string; end?: string; last?: string }
): T[] {
  if (!params) return items;
  let filtered = [...items];

  const getTimestamp = (item: T): string => {
    return item.timestamp || item.detected_at || "";
  };

  if (params.last) {
    const match = params.last.match(/^(\d+)([hdwmy])$/);
    if (match) {
      const amount = parseInt(match[1], 10);
      const unit = match[2];
      const cutoff = new Date();
      
      if (unit === "h") cutoff.setHours(cutoff.getHours() - amount);
      else if (unit === "d") cutoff.setDate(cutoff.getDate() - amount);
      else if (unit === "w") cutoff.setDate(cutoff.getDate() - amount * 7);
      else if (unit === "m") cutoff.setMonth(cutoff.getMonth() - amount);
      else if (unit === "y") cutoff.setFullYear(cutoff.getFullYear() - amount);
      
      filtered = filtered.filter(item => {
        const ts = getTimestamp(item);
        return ts ? new Date(ts) >= cutoff : true;
      });
    }
  } else {
    if (params.start) {
      const startLimit = new Date(params.start);
      filtered = filtered.filter(item => {
        const ts = getTimestamp(item);
        return ts ? new Date(ts) >= startLimit : true;
      });
    }
    if (params.end) {
      const endLimit = new Date(params.end);
      filtered = filtered.filter(item => {
        const ts = getTimestamp(item);
        return ts ? new Date(ts) <= endLimit : true;
      });
    }
  }

  return filtered;
}

// ─── Generators ──────────────────────────────────────────

export function generateMultiWeekReadingsForPatient(patientId: number, weeks = 4): GlucoseReading[] {
  const readings: GlucoseReading[] = [];
  const now = new Date();
  const totalMinutes = weeks * 7 * 24 * 60;
  const intervals = Math.ceil(totalMinutes / 5);

  let glucose = 5.5 + (patientId % 3) * 0.8;

  for (let i = intervals; i >= 0; i--) {
    const timestamp = new Date(now.getTime() - i * 5 * 60 * 1000);
    const hour = timestamp.getHours();

    const mealEffect =
      (hour >= 7 && hour <= 9) ||
      (hour >= 12 && hour <= 14) ||
      (hour >= 18 && hour <= 20)
        ? Math.random() * 0.18
        : 0;

    const eventEffect = Math.random() < 0.005 ? (Math.random() - 0.3) * 2.0 : 0;

    const baseline = 5.8 + (patientId % 4) * 0.4;
    glucose +=
      (baseline - glucose) * 0.018 +
      (Math.random() - 0.5) * 0.32 +
      mealEffect +
      eventEffect;
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
      id: (patientId * 100000) + (intervals - i),
      patient_id: patientId,
      timestamp: timestamp.toISOString(),
      glucose_mmoll: Math.round(glucose * 10) / 10,
      source: "simulated",
      status,
    });
  }
  return readings;
}

export function generateMealsAndInsulinForReadings(
  patientId: number,
  readings: GlucoseReading[]
): { meals: MealEvent[]; insulins: InsulinEvent[] } {
  const meals: MealEvent[] = [];
  const insulins: InsulinEvent[] = [];

  if (readings.length === 0) return { meals, insulins };

  const datesSet = new Set<string>();
  readings.forEach((r) => {
    const dStr = r.timestamp.slice(0, 10);
    datesSet.add(dStr);
  });

  let eventId = 1;
  const dates = Array.from(datesSet).sort();

  dates.forEach((dStr) => {
    const mealTimeBreakfast = new Date(`${dStr}T08:15:00Z`);
    meals.push({
      id: (patientId * 200000) + eventId++,
      patient_id: patientId,
      timestamp: mealTimeBreakfast.toISOString(),
      carbs: Math.round(45 + Math.random() * 15),
      meal_type: "breakfast",
    });
    insulins.push({
      id: (patientId * 300000) + eventId++,
      patient_id: patientId,
      timestamp: new Date(mealTimeBreakfast.getTime() - 15 * 60 * 1000).toISOString(),
      units: Math.round(5 + Math.random() * 3),
      event_type: "bolus",
    });

    const mealTimeLunch = new Date(`${dStr}T12:45:00Z`);
    meals.push({
      id: (patientId * 200000) + eventId++,
      patient_id: patientId,
      timestamp: mealTimeLunch.toISOString(),
      carbs: Math.round(65 + Math.random() * 20),
      meal_type: "lunch",
    });
    insulins.push({
      id: (patientId * 300000) + eventId++,
      patient_id: patientId,
      timestamp: new Date(mealTimeLunch.getTime() - 10 * 60 * 1000).toISOString(),
      units: Math.round(7 + Math.random() * 4),
      event_type: "bolus",
    });

    if (Math.random() > 0.3) {
      const mealTimeSnack = new Date(`${dStr}T15:30:00Z`);
      meals.push({
        id: (patientId * 200000) + eventId++,
        patient_id: patientId,
        timestamp: mealTimeSnack.toISOString(),
        carbs: Math.round(20 + Math.random() * 10),
        meal_type: "snack",
      });
      insulins.push({
        id: (patientId * 300000) + eventId++,
        patient_id: patientId,
        timestamp: mealTimeSnack.toISOString(),
        units: Math.round(2 + Math.random() * 2),
        event_type: "bolus",
      });
    }

    const mealTimeDinner = new Date(`${dStr}T19:00:00Z`);
    meals.push({
      id: (patientId * 200000) + eventId++,
      patient_id: patientId,
      timestamp: mealTimeDinner.toISOString(),
      carbs: Math.round(70 + Math.random() * 25),
      meal_type: "dinner",
    });
    insulins.push({
      id: (patientId * 300000) + eventId++,
      patient_id: patientId,
      timestamp: new Date(mealTimeDinner.getTime() - 5 * 60 * 1000).toISOString(),
      units: Math.round(8 + Math.random() * 5),
      event_type: "bolus",
    });

    insulins.push({
      id: (patientId * 300000) + eventId++,
      patient_id: patientId,
      timestamp: new Date(`${dStr}T22:00:00Z`).toISOString(),
      units: Math.round(18 + Math.random() * 4),
      event_type: "basal",
    });
  });

  return { meals, insulins };
}

// ─── Initialization ────────────────────────────────────────

export function ensureStateInitialized() {
  if (stateInitialized) return;
  stateInitialized = true;

  patientsList = DEMO_PATIENTS_SEEDS.map(p => ({
    id: p.id,
    external_id: p.external_id,
    name: p.name,
    age: p.age
  }));

  patientsList.forEach((p) => {
    const readings = generateMultiWeekReadingsForPatient(p.id);
    glucoseReadingsMap[p.id] = readings;

    const { meals, insulins } = generateMealsAndInsulinForReadings(p.id, readings);
    mealEventsMap[p.id] = meals;
    insulinEventsMap[p.id] = insulins;

    const baseAnomalies = SEED_ANOMALIES[p.id] || [];
    anomaliesMap[p.id] = baseAnomalies.map((anom) => ({
      ...anom,
      patient_id: p.id,
    }));
  });
}

// ─── API Implementation Functions ─────────────────────────

export function getDemoPatients(
  page = 1,
  perPage = 20,
  sortBy?: string,
  sortDir?: string
): PaginatedResponse<Patient> {
  ensureStateInitialized();
  const list = [...patientsList];

  if (sortBy) {
    list.sort((a, b) => {
      let valA: string | number = "";
      let valB: string | number = "";
      if (sortBy === "name") {
        valA = a.name;
        valB = b.name;
      } else if (sortBy === "ext_id" || sortBy === "external_id") {
        valA = a.external_id;
        valB = b.external_id;
      } else if (sortBy === "age") {
        valA = Number(a.age) || 0;
        valB = Number(b.age) || 0;
      }

      if (valA < valB) return sortDir === "desc" ? 1 : -1;
      if (valA > valB) return sortDir === "desc" ? -1 : 1;
      return 0;
    });
  }

  const total = list.length;
  const startIndex = (page - 1) * perPage;
  const endIndex = startIndex + perPage;
  const paginated = list.slice(startIndex, endIndex);

  return {
    patients: paginated,
    total,
    page,
    pages: Math.ceil(total / perPage),
  };
}

export function getDemoPatient(patientId: number): Patient {
  ensureStateInitialized();
  const p = patientsList.find(x => x.id === patientId);
  if (!p) throw new Error("Patient not found");
  return p;
}

export function getDemoPatientByExternalId(externalId: string): Patient {
  ensureStateInitialized();
  const targetId = externalId === "SIM_000001" ? "DEMO_000001" : externalId;
  const p = patientsList.find(x => x.external_id === targetId);
  if (!p) throw new Error("Patient not found");
  return p;
}

export function createDemoPatient(patient: { external_id: string; name: string; date_of_birth?: string }): Patient {
  ensureStateInitialized();
  const existing = patientsList.find(x => x.external_id === patient.external_id);
  if (existing) {
    throw new Error("Patient external ID already exists");
  }
  
  let age = 35;
  if (patient.date_of_birth) {
    const birthYear = new Date(patient.date_of_birth).getFullYear();
    age = new Date().getFullYear() - birthYear;
  }

  const newPatient: Patient = {
    id: patientsList.length + 1,
    external_id: patient.external_id,
    name: patient.name,
    age,
  };

  patientsList.push(newPatient);

  const readings = generateMultiWeekReadingsForPatient(newPatient.id);
  glucoseReadingsMap[newPatient.id] = readings;

  const { meals, insulins } = generateMealsAndInsulinForReadings(newPatient.id, readings);
  mealEventsMap[newPatient.id] = meals;
  insulinEventsMap[newPatient.id] = insulins;
  anomaliesMap[newPatient.id] = [];

  return newPatient;
}

export function getDemoGlucoseReadings(
  patientId: number,
  params?: { start?: string; end?: string; last?: string }
): { patient_id: number; readings: GlucoseReading[]; count: number } {
  ensureStateInitialized();
  const allReadings = glucoseReadingsMap[patientId] || [];
  const filtered = filterByTimeParams(allReadings, params);
  const sorted = filtered.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
  return {
    patient_id: patientId,
    readings: sorted,
    count: sorted.length
  };
}

export function getDemoLatestReading(patientId: number): GlucoseReading {
  ensureStateInitialized();
  const allReadings = glucoseReadingsMap[patientId] || [];
  if (allReadings.length === 0) {
    throw new Error("No readings found");
  }
  return allReadings.reduce((latest, r) => new Date(r.timestamp) > new Date(latest.timestamp) ? r : latest);
}

export function getDemoTimeInRange(
  patientId: number,
  params?: { start?: string; end?: string; last?: string; VeryLow?: number; Low?: number; High?: number; VeryHigh?: number }
): TimeInRange {
  ensureStateInitialized();
  const allReadings = glucoseReadingsMap[patientId] || [];
  const filtered = filterByTimeParams(allReadings, params);

  const vLowThreshold = params?.VeryLow ?? VERY_LOW_THRESHOLD;
  const lowThreshold = params?.Low ?? LOW_THRESHOLD;
  const highThreshold = params?.High ?? HIGH_THRESHOLD;
  const vHighThreshold = params?.VeryHigh ?? VERY_HIGH_THRESHOLD;

  if (filtered.length === 0) {
    return {
      patient_id: patientId,
      temporal_span_days: 7,
      very_low_pct: 0,
      low_pct: 0,
      in_range_pct: 100,
      high_pct: 0,
      very_high_pct: 0
    };
  }

  let vLowCount = 0;
  let lowCount = 0;
  let inRangeCount = 0;
  let highCount = 0;
  let vHighCount = 0;

  filtered.forEach((r) => {
    const val = r.glucose_mmoll;
    if (val < vLowThreshold) vLowCount++;
    else if (val < lowThreshold) lowCount++;
    else if (val <= highThreshold) inRangeCount++;
    else if (val <= vHighThreshold) highCount++;
    else vHighCount++;
  });

  const total = filtered.length;
  const roundPct = (count: number) => Math.round((count / total) * 1000) / 10;

  return {
    patient_id: patientId,
    temporal_span_days: getSpanDays(params?.last),
    very_low_pct: roundPct(vLowCount),
    low_pct: roundPct(lowCount),
    in_range_pct: roundPct(inRangeCount),
    high_pct: roundPct(highCount),
    very_high_pct: roundPct(vHighCount)
  };
}

export function getDemoAverageReading(
  patientId: number,
  params?: { start?: string; end?: string; last?: string }
): number {
  ensureStateInitialized();
  const allReadings = glucoseReadingsMap[patientId] || [];
  const filtered = filterByTimeParams(allReadings, params);
  if (filtered.length === 0) return 6.0;
  const sum = filtered.reduce((acc, r) => acc + r.glucose_mmoll, 0);
  return Math.round((sum / filtered.length) * 10) / 10;
}

export function getDemoHbA1c(
  patientId: number,
  params?: { start?: string; end?: string; last?: string }
): HbA1c {
  const avg = getDemoAverageReading(patientId, params);
  const percent = Math.round(((avg + 2.59) / 1.594) * 10) / 10;
  const mmol_per_mol = Math.round((percent - 2.15) * 10.929);
  return {
    patient_id: patientId,
    percent,
    mmol_per_mol
  };
}

export function getDemoGmi(
  patientId: number,
  params?: { start?: string; end?: string; last?: string }
): Gmi {
  const avg = getDemoAverageReading(patientId, params);
  const avgMgdl = avg * 18.0155;
  const gmiVal = Math.round((3.31 + 0.02392 * avgMgdl) * 10) / 10;
  return {
    patient_id: patientId,
    gmi: gmiVal
  };
}

export function getDemoScatterplot(
  patientId: number,
  params?: { start?: string; end?: string; last?: string }
): ScatterplotData {
  ensureStateInitialized();
  const allReadings = glucoseReadingsMap[patientId] || [];
  const filtered = filterByTimeParams(allReadings, params);

  const groups: Record<string, number[]> = {};
  filtered.forEach((r) => {
    const dStr = r.timestamp.slice(0, 10);
    if (!groups[dStr]) groups[dStr] = [];
    groups[dStr].push(r.glucose_mmoll);
  });

  const points: DailyGlucosePoint[] = Object.keys(groups).map((date) => {
    const vals = groups[date];
    const sum = vals.reduce((a, b) => a + b, 0);
    return {
      date,
      average: Math.round((sum / vals.length) * 10) / 10,
      min: Math.min(...vals),
      max: Math.max(...vals)
    };
  });

  points.sort((a, b) => a.date.localeCompare(b.date));

  return {
    patient_id: patientId,
    points,
    count: points.length
  };
}

export function getDemoAnomalies(
  patientId: number,
  params?: { start?: string; end?: string; last?: string }
): { patient_id: number; anomalies: AnomalyDetection[]; count: number } {
  ensureStateInitialized();
  const allAnom = anomaliesMap[patientId] || [];
  const filtered = filterByTimeParams(allAnom, params);
  return {
    patient_id: patientId,
    anomalies: filtered,
    count: filtered.length
  };
}

export async function runDemoDetection(
  patientId: number,
  params?: { start?: string; end?: string; last?: string }
): Promise<{ patient_id: number; anomalies: AnomalyDetection[]; count: number }> {
  await new Promise(resolve => setTimeout(resolve, 500));
  return getDemoAnomalies(patientId, params);
}

export function acknowledgeDemoAnomaly(
  patientId: number,
  anomalyId: number
): AnomalyDetection {
  ensureStateInitialized();
  const allAnom = anomaliesMap[patientId] || [];
  const anomaly = allAnom.find(x => x.id === anomalyId);
  if (!anomaly) {
    throw new Error("Anomaly not found");
  }
  anomaly.is_acknowledged = true;
  return anomaly;
}

export function getDemoInsulins(
  patientId: number,
  params?: { start?: string; end?: string; last?: string }
): { patient_id: number; insulins: InsulinEvent[]; count: number } {
  ensureStateInitialized();
  const allInsulin = insulinEventsMap[patientId] || [];
  const filtered = filterByTimeParams(allInsulin, params);
  return {
    patient_id: patientId,
    insulins: filtered,
    count: filtered.length
  };
}

export function getDemoMeals(
  patientId: number,
  params?: { start?: string; end?: string; last?: string }
): { patient_id: number; meals: MealEvent[]; count: number } {
  ensureStateInitialized();
  const allMeals = mealEventsMap[patientId] || [];
  const filtered = filterByTimeParams(allMeals, params);
  return {
    patient_id: patientId,
    meals: filtered,
    count: filtered.length
  };
}

export async function simulateUploadCsv(patientId: number, file: File) {
  console.log(`DemoMode: CSV upload simulation for patient ${patientId} (file: ${file.name})`);
  await new Promise(resolve => setTimeout(resolve, 1000));
  return {
    message: "CSV File parsed successfully (Demo Mode)",
    glucose_count: 288,
    meal_count: 4,
    insulin_count: 5,
    date_from: new Date(Date.now() - 24 * 3600 * 1000).toISOString(),
    date_to: new Date().toISOString()
  };
}

export async function simulateUploadGlookoZip(patientId: number, file: File) {
  console.log(`DemoMode: ZIP upload simulation for patient ${patientId} (file: ${file.name})`);
  await new Promise(resolve => setTimeout(resolve, 1500));
  return {
    message: "Glooko ZIP parsed successfully (Demo Mode)",
    glucose_count: 1440,
    meal_count: 20,
    insulin_count: 25,
    date_from: new Date(Date.now() - 5 * 24 * 3600 * 1000).toISOString(),
    date_to: new Date().toISOString()
  };
}

export async function simulateUploadParquet(file: File) {
  console.log(`DemoMode: Parquet upload simulation (file: ${file.name})`);
  await new Promise(resolve => setTimeout(resolve, 2000));
  return {
    message: "Parquet Cohort simulation uploaded successfully (Demo Mode)",
    patients_count: 5,
    glucose_count: 10000,
    meal_count: 150,
    insulin_count: 200
  };
}

// ─── Deprecated / Old API Compat ──────────────────────────

export function generateMultiWeekReadings(weeks = 4): GlucoseReading[] {
  return generateMultiWeekReadingsForPatient(1, weeks);
}

export function generateDemoReadings(): GlucoseReading[] {
  return generateMultiWeekReadingsForPatient(1, 1);
}

export const DEMO_PATIENTS: Array<{
  patient: Patient;
  latestReading: GlucoseReading;
  tir: TimeInRange;
  anomalyCount: number;
}> = []; // Deprecated - replaced by state-based functions
