"use client";

import { useState, useCallback } from "react";
import GlucoseChart from "@/views/GlucoseChart/GlucoseChart";
import TIRChart, { RangesModal } from "@/views/TIRChart/TIRChart";
import MultiWeeklyChart from "@/views/MultiWeeklyChart/MultiWeeklyChart";
import PatientOverview from "@/views/PatientOverview/PatientOverview";
import AnomalyAlert from "@/views/AnomalyAlert/AnomalyAlert";
import InsulinDailyChart from "@/views/InsulinDailyChart/InsulinDailyChart";
import CarboDailyChart from "@/views/CarboDailyChart/CarboDailyChart";
import GlucoseScatterplot from "@/views/GlucoseScatterplot/GlucoseScatterplot";
import { usePatientController } from "@/controllers/usePatientController";
import { useTimeRange, parseLast } from "@/controllers/TimeRangeContext";
import { useGlucoseRanges } from "@/controllers/GlucoseRangesContext";
import { useGlucoseUnit } from "@/controllers/GlucoseUnitContext";
import styles from "./patient.module.css";

/**
 * Patient Dashboard — thin shell.
 * All data and business logic lives in usePatientController.
 */
export default function PatientDashboard() {
  const {
    loading,
    error,
    patient,
    readings,
    multiWeekReadings,
    tir,
    anomalies,
    latestReading,
    unacknowledgedCount,
    handleAcknowledge,
    averageGlucose,
    hba1c,
    gmi,
    scatterplotData,
  } = usePatientController();

  const { timeRange, setLast } = useTimeRange();
  const { ranges: glucoseRanges, setRanges: onThresholdsChange } = useGlucoseRanges();
  const { unit } = useGlucoseUnit();
  const [showRangesModal, setShowRangesModal] = useState(false);

  // Shared daily-view state — GlucoseChart is the source of truth
  const [dailyOffset, setDailyOffset] = useState(0);
  const [glucoseLatestDay, setGlucoseLatestDay] = useState<Date | null>(null);

  const handleGlucoseOffsetChange = useCallback((offset: number, latestDay: Date | null) => {
    setDailyOffset(offset);
    setGlucoseLatestDay(latestDay);
  }, []);

  const handleGlucoseLatestDayResolved = useCallback((day: Date) => {
    setGlucoseLatestDay(day);
  }, []);

  const { value: activeVal, unit: activeUnit } = parseLast(timeRange.last);
  const maxVal = activeUnit === "d" ? 7 : activeUnit === "w" ? 4 : 6;
  const valuesArray = Array.from({ length: maxVal }, (_, i) => i + 1);

  const handleUnitChange = (newUnit: "d" | "w" | "m") => {
    let newValue = activeVal;
    if (newUnit === "d") {
      newValue = Math.min(Math.max(activeVal, 1), 7);
    } else if (newUnit === "w") {
      newValue = Math.min(Math.max(activeVal, 1), 4);
    } else if (newUnit === "m") {
      newValue = Math.min(Math.max(activeVal, 1), 6);
    }
    setLast(`${newValue}${newUnit}`);
  };

  const handleValueChange = (newValue: number) => {
    setLast(`${newValue}${activeUnit}`);
  };

  if (loading) {
    return (
      <div className={styles.dashboard}>
        <p style={{ color: "var(--text-secondary)", marginTop: "2rem" }}>
          Loading dashboard data…
        </p>
      </div>
    );
  }

  if (error) {
    return (
      <div className={styles.dashboard}>
        <p style={{ color: "var(--color-high)", marginTop: "2rem" }}>
          Error: {error}
        </p>
      </div>
    );
  }

  return (
    <div className={styles.dashboard}>
      <div className={styles.titleRow}>
        <h2 className={styles.pageTitle}>Patient Dashboard</h2>
        <div className={styles.controls}>
          <div className={styles.timeRangeSelector}>
            <span className={styles.selectorLabel}>Last</span>
            <select
              className={styles.selectInput}
              value={activeVal}
              onChange={(e) => handleValueChange(Number(e.target.value))}
            >
              {valuesArray.map((val) => (
                <option key={val} value={val}>
                  {val}
                </option>
              ))}
            </select>
            <select
              className={styles.selectInput}
              value={activeUnit}
              onChange={(e) => handleUnitChange(e.target.value as "d" | "w" | "m")}
            >
              <option value="d">Days</option>
              <option value="w">Weeks</option>
              <option value="m">Months</option>
            </select>
          </div>

          <button
            id="page-customize-ranges-btn"
            className={`${styles.rangesBtn} ${
              showRangesModal ? styles.rangesBtnActive : ""
            }`}
            onClick={() => setShowRangesModal(true)}
            title="Customize glucose ranges"
          >
            <svg
              width="13"
              height="13"
              viewBox="0 0 20 20"
              fill="currentColor"
              aria-hidden="true"
            >
              <path
                fillRule="evenodd"
                clipRule="evenodd"
                d="M11.49 3.17c-.38-1.56-2.6-1.56-2.98 0a1.532 1.532 0 01-2.286.948c-1.372-.836-2.942.734-2.106 2.106.54.886.061 2.042-.947 2.287-1.561.379-1.561 2.6 0 2.978a1.532 1.532 0 01.947 2.287c-.836 1.372.734 2.942 2.106 2.106a1.532 1.532 0 012.287.947c.379 1.561 2.6 1.561 2.978 0a1.533 1.533 0 012.287-.947c1.372.836 2.942-.734 2.106-2.106a1.533 1.533 0 01.947-2.287c1.561-.379 1.561-2.6 0-2.978a1.532 1.532 0 01-.947-2.287c.836-1.372-.734-2.942-2.106-2.106a1.532 1.532 0 01-2.287-.947zM10 13a3 3 0 100-6 3 3 0 000 6z"
              />
            </svg>
            Custom Ranges
          </button>
        </div>
      </div>

      <PatientOverview
        patientName={patient!.name}
        patientId={patient!.external_id}
        patientAge={patient!.age}
        latestReading={latestReading}
        tir={tir ?? undefined}
        anomalyCount={unacknowledgedCount}
        averageGlucose={averageGlucose}
        timeRangeLast={timeRange.last}
        hba1c={hba1c ?? undefined}
        gmi={gmi ?? undefined}
      />

      {anomalies.length > 0 && (
        <AnomalyAlert anomalies={anomalies} onAcknowledge={handleAcknowledge} />
      )}

      <div className={styles.chartsGrid}>
        <GlucoseChart
          readings={readings}
          patientId={patient!.id}
          onOffsetChange={handleGlucoseOffsetChange}
          onLatestDayResolved={handleGlucoseLatestDayResolved}
        />
        {tir && (
          <TIRChart
            tir={tir}
            patientId={patient!.id}
          />
        )}
      </div>

      <div className={styles.chartsGridHalf}>
        <InsulinDailyChart
          patientId={patient!.id}
          syncOffset={dailyOffset}
          syncLatestDay={glucoseLatestDay}
        />
        <CarboDailyChart
          patientId={patient!.id}
          syncOffset={dailyOffset}
          syncLatestDay={glucoseLatestDay}
        />
      </div>

      <MultiWeeklyChart readings={multiWeekReadings} />

      {scatterplotData && (
        <GlucoseScatterplot
          points={scatterplotData.points}
          patientId={patient!.id}
        />
      )}

      {showRangesModal && (
        <RangesModal
          unit={unit}
          thresholds={glucoseRanges}
          onApply={onThresholdsChange}
          onClose={() => setShowRangesModal(false)}
        />
      )}
    </div>
  );
}
