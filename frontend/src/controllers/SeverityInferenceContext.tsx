"use client";

import { createContext, useContext, useState, useCallback, type ReactNode } from "react";

/**
 * Holds the two knobs the anomaly feature adds:
 *   - inferenceEnabled: when ON, the page runs ML detection (POST /api/anomaly/detect)
 *     for the current window before reading; when OFF, it only reads stored anomalies.
 *   - minSeverity: the DISPLAY threshold in σ above the patient's baseline. Range 2σ–6σ,
 *     default 3σ. Applied client-side in AnomalyAlert — the slider never triggers a refetch.
 *     Shown to the user as a 0–100% scale (nobody thinks in σ): higher % = stricter = fewer,
 *     stronger anomalies. The mapping is pct = 50 + (σ−2)·10, so 2σ→50%, 3σ→60%, … 6σ→90%.
 *     Slider steps 1σ (= 10%).
 */
export const SEVERITY_MIN = 6;     // σ, slider minimum  → 50%
export const SEVERITY_MAX = 10;     // σ, slider maximum  → 90%
export const SEVERITY_STEP = 1;    // σ per slider step  (= 10%)
const SEVERITY_DEFAULT = 6;        // σ, default         → 60%

/** Map a σ threshold to the user-facing percentage label. */
export function severityToPct(sigma: number): number {
  return 50 + (sigma - SEVERITY_MIN) * 10;
}

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
