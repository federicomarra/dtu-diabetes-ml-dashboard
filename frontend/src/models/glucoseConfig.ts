/**
 * Clinical glucose thresholds configuration.
 *
 * All values are in mmol/L (the canonical unit throughout the system).
 * These thresholds follow the international consensus on
 * Time-in-Range targets (Battelino et al., Diabetes Care 2019).
 *
 * Adjust values here to change classification boundaries everywhere
 * in the application — charts, status labels, demo data, etc.
 */

// ─── Clinical range thresholds (mmol/L) ───────────────────

import config from '../../glucose-config.json';

/** Below this value a reading is classified as "very low" (level 2 hypoglycaemia). */
export const VERY_LOW_THRESHOLD = config.VERY_LOW_THRESHOLD;

/** Below this value (but ≥ VERY_LOW) a reading is classified as "low" (level 1 hypoglycaemia). */
export const LOW_THRESHOLD = config.LOW_THRESHOLD;

/** At or below this value (and ≥ LOW) a reading is classified as "in range". */
export const HIGH_THRESHOLD = config.HIGH_THRESHOLD;

/** Above HIGH but ≤ this value a reading is classified as "high" (level 1 hyperglycaemia). */
export const VERY_HIGH_THRESHOLD = config.VERY_HIGH_THRESHOLD;

// ─── Chart display bounds (mmol/L) ────────────────────────

/** Lower bound for the Y-axis domain on glucose charts. */
export const CHART_DOMAIN_MIN = 2.2;

/** Upper bound for the Y-axis domain on glucose charts. */
export const CHART_DOMAIN_MAX = 19.4;

/** Absolute floor used to clamp simulated / generated glucose values. */
export const GLUCOSE_CLAMP_MIN = 2.8;

/** Absolute ceiling used to clamp simulated / generated glucose values. */
export const GLUCOSE_CLAMP_MAX = 19.4;
