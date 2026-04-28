"use client";

import { createContext, useContext, useState, useCallback, type ReactNode } from "react";
import type { GlucoseUnit } from "@/models/glucoseUnits";

interface GlucoseUnitContextValue {
  unit: GlucoseUnit;
  toggleUnit: () => void;
}

const GlucoseUnitContext = createContext<GlucoseUnitContextValue | undefined>(undefined);

export function GlucoseUnitProvider({ children }: { children: ReactNode }) {
  const [unit, setUnit] = useState<GlucoseUnit>("mmol/L");

  const toggleUnit = useCallback(() => {
    setUnit((prev) => (prev === "mmol/L" ? "mg/dL" : "mmol/L"));
  }, []);

  return (
    <GlucoseUnitContext.Provider value={{ unit, toggleUnit }}>
      {children}
    </GlucoseUnitContext.Provider>
  );
}

/** Hook to access the current glucose unit and toggle function. */
export function useGlucoseUnit(): GlucoseUnitContextValue {
  const ctx = useContext(GlucoseUnitContext);
  if (!ctx) {
    throw new Error("useGlucoseUnit must be used within a GlucoseUnitProvider");
  }
  return ctx;
}
