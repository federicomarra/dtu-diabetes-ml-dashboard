"use client";

import { createContext, useContext, useState, useCallback, type ReactNode } from "react";

/**
 * Holds the two knobs the anomaly feature adds:
 *   - inferenceEnabled: when ON, the page runs ML detection (POST /api/anomaly/detect)
 *     for the current window before reading; when OFF, it only reads stored anomalies.
 *   - minSeverity: the DISPLAY threshold in σ above the patient's baseline. Applied
 *     client-side in AnomalyAlert — the slider never triggers a refetch.
 *
 * σ here is a ROBUST z-score of a forecast-surprise statistic, not a Gaussian sigma: the
 * score distribution has skew ~7, so a "6σ" window occurs about once in 27, not once in a
 * billion. It is a sound sort key and a worthless rarity claim. The UI therefore never shows
 * σ as a percentage or a confidence — it shows how many events the threshold surfaces and at
 * what daily rate. See ml/docs/DETECTION_SEVERITY.md §1 and §10.
 */
export const SEVERITY_MIN = 6;     // σ, slider minimum (loosest)
export const SEVERITY_MAX = 10;    // σ, slider maximum (strictest)
export const SEVERITY_STEP = 1;    // σ per slider step
const SEVERITY_DEFAULT = 6;        // σ, default

interface SeverityInferenceContextValue {
  inferenceEnabled: boolean;
  setInferenceEnabled: (enabled: boolean) => void;
  minSeverity: number;               // σ — display-only threshold; drives the slider (client-side filter)
  setMinSeverity: (sigma: number) => void;
  resetMinSeverity: () => void;
}

const SeverityInferenceContext = createContext<SeverityInferenceContextValue | undefined>(undefined);

export function SeverityInferenceProvider({ children }: { children: ReactNode }) {
  const [inferenceEnabled, setInferenceEnabled] = useState(false);
  const [minSeverity, setMinSeverity] = useState(SEVERITY_DEFAULT);

  const resetMinSeverity = useCallback(() => setMinSeverity(SEVERITY_DEFAULT), []);

  return (
    <SeverityInferenceContext.Provider
      value={{ inferenceEnabled, setInferenceEnabled, minSeverity, setMinSeverity, resetMinSeverity }}
    >
      {children}
    </SeverityInferenceContext.Provider>
  );
}

/** Hook to access the inference toggle and the severity threshold (σ, shown as %). */
export function useSeverityInference(): SeverityInferenceContextValue {
  const ctx = useContext(SeverityInferenceContext);
  if (!ctx) {
    throw new Error("useSeverityInference must be used within a SeverityInferenceProvider");
  }
  return ctx;
}
