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
