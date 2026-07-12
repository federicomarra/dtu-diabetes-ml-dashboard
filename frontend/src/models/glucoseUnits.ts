/**
 * Glucose unit conversion utilities.
 *
 * The canonical unit throughout the system is mmol/L.
 * This module provides helpers to convert and format values
 * when the user switches to mg/dL for display purposes.
 */

export type GlucoseUnit = "mmol/L" | "mg/dL";

/** 1 mmol/L ≈ 18.0182 mg/dL */
const CONVERSION_FACTOR = 18.0182;

/** Convert a value from mmol/L to the target unit. */
export function convertGlucose(mmoll: number, unit: GlucoseUnit): number {
  if (unit === "mg/dL") {
    return Math.round(mmoll * CONVERSION_FACTOR);
  }
  return Math.round(mmoll * 10) / 10; // keep 1 decimal for mmol/L
}

/** Format a glucose value with its unit label. */
export function formatGlucose(mmoll: number, unit: GlucoseUnit): string {
  const value = convertGlucose(mmoll, unit);
  return `${unit === "mg/dL" ? value : value.toFixed(1)} ${unit}`;
}

/**
 * Convert clinical threshold values from mmol/L to the target unit.
 * Used by charts for reference lines and domains.
 */
export function convertThreshold(mmoll: number, unit: GlucoseUnit): number {
  return convertGlucose(mmoll, unit);
}

/**
 * Plain-language evidence for one anomaly, in the user's chosen unit.
 *
 * The ML service also sends a `description`, but it hardcodes mmol/L — so we compose
 * from the signed `residual_mmoll` instead and fall back to the server sentence only
 * when the number is missing (anomalies detected before this field existed).
 *
 * The sign is the meaning: positive = glucose ran ABOVE the model's forecast, which is
 * what a missed bolus looks like. A late bolus can legitimately run below, once the
 * delayed dose lands.
 */
export function describeAnomaly(
  residualMmoll: number | undefined,
  durationMin: number | undefined,
  anomalyType: string,
  unit: GlucoseUnit,
  fallback: string | null
): string | null {
  if (residualMmoll == null || durationMin == null) return fallback;

  const magnitude = formatGlucose(Math.abs(residualMmoll), unit);
  const direction = residualMmoll >= 0 ? "above" : "below";
  const cause =
    anomalyType === "late_bolus"
      ? "covering bolus arrived late"
      : "no bolus logged around the rise";

  return `Glucose ran ${magnitude} ${direction} forecast for ${durationMin} min · ${cause}`;
}

/**
 * Excursion size: total excess glucose above (or below) the forecast, in mmol/L·min.
 *
 * This is the AREA over the forecast, not the peak deviation — a 4 mmol/L overshoot
 * sustained for 195 min is a bigger excursion than an 8 mmol/L spike lasting 30 min,
 * and only the area says so. It is a separate question from `severity`: severity ranks
 * by how UNEXPECTED an event was given insulin and carbs, this ranks by how much excess
 * glucose the patient actually experienced. The two genuinely disagree
 * (Spearman ≈ 0.47 on real data) — see ml/docs/DETECTION_SEVERITY.md.
 */
export function excursionSize(
  residualMmoll: number | undefined,
  durationMin: number | undefined
): number {
  if (residualMmoll == null || durationMin == null) return 0;
  return Math.abs(residualMmoll) * durationMin;
}

/** Excursion size in the user's unit, e.g. "429 mmol/L·min" or "7,733 mg/dL·min". */
export function formatExcursionSize(
  residualMmoll: number | undefined,
  durationMin: number | undefined,
  unit: GlucoseUnit
): string | null {
  const area = excursionSize(residualMmoll, durationMin);
  if (area === 0) return null;
  const scaled = unit === "mg/dL" ? area * 18.0182 : area;
  return `${Math.round(scaled).toLocaleString()} ${unit}·min`;
}
