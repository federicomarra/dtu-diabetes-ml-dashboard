"use client";

import { createContext, useContext, useState, useCallback, type ReactNode } from "react";
import {
  VERY_LOW_THRESHOLD,
  LOW_THRESHOLD,
  HIGH_THRESHOLD,
  VERY_HIGH_THRESHOLD,
} from "@/models/glucoseConfig";

export interface GlucoseRanges {
  veryHigh: number; // mmol/L
  high: number;     // mmol/L
  low: number;      // mmol/L
  veryLow: number;  // mmol/L
}

export const DEFAULT_THRESHOLDS: GlucoseRanges = {
  veryHigh: VERY_HIGH_THRESHOLD,
  high: HIGH_THRESHOLD,
  low: LOW_THRESHOLD,
  veryLow: VERY_LOW_THRESHOLD,
};

interface GlucoseRangesContextValue {
  ranges: GlucoseRanges;
  setRanges: (ranges: GlucoseRanges) => void;
  resetRanges: () => void;
}

const GlucoseRangesContext = createContext<GlucoseRangesContextValue | undefined>(undefined);

export function GlucoseRangesProvider({ children }: { children: ReactNode }) {
  const [ranges, setRangesRaw] = useState<GlucoseRanges>(DEFAULT_THRESHOLDS);

  const setRanges = useCallback((newRanges: GlucoseRanges) => {
    setRangesRaw(newRanges);
  }, []);

  const resetRanges = useCallback(() => {
    setRangesRaw(DEFAULT_THRESHOLDS);
  }, []);

  return (
    <GlucoseRangesContext.Provider value={{ ranges, setRanges, resetRanges }}>
      {children}
    </GlucoseRangesContext.Provider>
  );
}

/** Hook to access the current glucose range thresholds and setters. */
export function useGlucoseRanges(): GlucoseRangesContextValue {
  const ctx = useContext(GlucoseRangesContext);
  if (!ctx) {
    throw new Error("useGlucoseRanges must be used within a GlucoseRangesProvider");
  }
  return ctx;
}
