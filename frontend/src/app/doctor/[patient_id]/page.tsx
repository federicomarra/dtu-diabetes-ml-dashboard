"use client";

import { useState, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import GlucoseChart from "@/views/GlucoseChart/GlucoseChart";
import TIRChart, { RangesModal } from "@/views/TIRChart/TIRChart";
import PatientOverview from "@/views/PatientOverview/PatientOverview";
import AnomalyAlert from "@/views/AnomalyAlert/AnomalyAlert";
import MultiWeeklyChart from "@/views/MultiWeeklyChart/MultiWeeklyChart";
import InsulinDailyChart from "@/views/InsulinDailyChart/InsulinDailyChart";
import CarboDailyChart from "@/views/CarboDailyChart/CarboDailyChart";
import GlucoseScatterplot from "@/views/GlucoseScatterplot/GlucoseScatterplot";
import { usePatientDetailController } from "@/controllers/usePatientDetailController";
import { useTimeRange, parseLast } from "@/controllers/TimeRangeContext";
import { useGlucoseRanges } from "@/controllers/GlucoseRangesContext";
import { useGlucoseUnit } from "@/controllers/GlucoseUnitContext";
import styles from "./patient-detail.module.css";

/**
 * Doctor — Patient Detail Page (/doctor/[patient_id]) — thin shell.
 * All data and business logic lives in usePatientDetailController.
 */
export default function DoctorPatientDetail() {
  const { patient_id } = useParams<{ patient_id: string }>();
  const ctrl = usePatientDetailController(patient_id);
  const { timeRange, setLast } = useTimeRange();
  const { ranges: glucoseRanges, setRanges: onThresholdsChange } = useGlucoseRanges();
  const { unit } = useGlucoseUnit();
  const [showRangesModal, setShowRangesModal] = useState(false);

  // Shared daily-view state — GlucoseChart is the source of truth
  const [dailyOffset, setDailyOffset] = useState(0);
  const [glucoseLatestDay, setGlucoseLatestDay] = useState<Date | null>(null);

  const [hasInsulin, setHasInsulin] = useState(true);
  const [hasCarbo, setHasCarbo] = useState(true);

  const handleInsulinPresence = useCallback((presence: boolean) => setHasInsulin(presence), []);
  const handleCarboPresence = useCallback((presence: boolean) => setHasCarbo(presence), []);

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

  if (ctrl.loading) {
    return (
      <div className={styles.dashboard}>
        <Link href="/doctor" className={styles.backLink}>
          <ArrowLeft size={16} /> Back to Doctor Dashboard
        </Link>
        <p style={{ color: "var(--text-secondary)", marginTop: "2rem" }}>
          Loading patient data…
        </p>
      </div>
    );
  }

  if (ctrl.notFound) {
    return (
      <div className={styles.notFound}>
        <p>
          Patient <code>{patient_id}</code> not found.
        </p>
        <Link href="/doctor" className={styles.backLink}>
          <ArrowLeft size={16} /> Back to Doctor Dashboard
        </Link>
      </div>
    );
  }

  if (ctrl.error) {
    return (
      <div className={styles.dashboard}>
        <Link href="/doctor" className={styles.backLink}>
          <ArrowLeft size={16} /> Back to Doctor Dashboard
        </Link>
        <p style={{ color: "var(--color-high)", marginTop: "2rem" }}>
          Error: {ctrl.error}
        </p>
      </div>
    );
  }

  const { patient, tir, readings, multiWeekReadings, anomalies, latestReading, averageGlucose, hba1c, gmi, scatterplotData, handleAcknowledge } =
    ctrl;

  const allChartsPresent = hasInsulin && hasCarbo;
  const onlyOneChart = (hasInsulin || hasCarbo) && !allChartsPresent;

  return (
    <div className={styles.dashboard}>
      <Link href="/doctor" className={styles.backLink}>
        <ArrowLeft size={16} />
        Back to Doctor Dashboard
      </Link>

      <div className={styles.titleRow}>
        <h2 className={styles.pageTitle}>Patient Detail View</h2>
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
        patientAge={patient!.age != null ? String(patient!.age) : "??"}
        latestReading={latestReading}
        tir={tir ?? undefined}
        anomalyCount={anomalies.filter((a) => !a.is_acknowledged).length}
        averageGlucose={averageGlucose}
        timeRangeLast={timeRange.last}
        hba1c={hba1c ?? undefined}
        gmi={gmi ?? undefined}
      />

      {anomalies.length > 0 && (
        <AnomalyAlert anomalies={anomalies} onAcknowledge={handleAcknowledge} />
      )}

      {/* Row 1: Glucose + TIR side-by-side when both charts present, else glucose full width */}
      <div className={allChartsPresent ? styles.chartsGrid : styles.chartsGridFull}>
        <GlucoseChart
          readings={readings}
          patientId={patient!.id}
          onOffsetChange={handleGlucoseOffsetChange}
          onLatestDayResolved={handleGlucoseLatestDayResolved}
        />
        {allChartsPresent && tir && (
          <TIRChart
            key="tir-top"
            tir={tir}
            patientId={patient!.id}
          />
        )}
      </div>

      {/* Row 2: layout depends on data availability */}
      {allChartsPresent ? (
        /* Both insulin & carbo → half-half */
        <div className={styles.chartsGridHalf}>
          <InsulinDailyChart
            key="insulin"
            patientId={patient!.id}
            syncOffset={dailyOffset}
            syncLatestDay={glucoseLatestDay}
            onDataPresence={handleInsulinPresence}
          />
          <CarboDailyChart
            key="carbo"
            patientId={patient!.id}
            syncOffset={dailyOffset}
            syncLatestDay={glucoseLatestDay}
            onDataPresence={handleCarboPresence}
          />
        </div>
      ) : onlyOneChart ? (
        /* Only one of insulin/carbo → TIR 1/3 left, chart 2/3 right */
        <div className={tir ? styles.chartsGridFlipped : styles.chartsGridFull}>
          {tir && (
            <TIRChart
              key="tir-bottom"
              tir={tir}
              patientId={patient!.id}
            />
          )}
          {hasInsulin && (
            <InsulinDailyChart
              key="insulin"
              patientId={patient!.id}
              syncOffset={dailyOffset}
              syncLatestDay={glucoseLatestDay}
              onDataPresence={handleInsulinPresence}
            />
          )}
          {hasCarbo && (
            <CarboDailyChart
              key="carbo"
              patientId={patient!.id}
              syncOffset={dailyOffset}
              syncLatestDay={glucoseLatestDay}
              onDataPresence={handleCarboPresence}
            />
          )}
        </div>
      ) : (
        /* No insulin/carbo at all → just TIR full width if available */
        <>
          {tir && (
            <div className={styles.chartsGridFull}>
              <TIRChart
                key="tir-bottom"
                tir={tir}
                patientId={patient!.id}
              />
            </div>
          )}
          {/* Hidden mounting points so onDataPresence callbacks still fire */}
          <div style={{ display: "none" }}>
            <InsulinDailyChart
              key="insulin"
              patientId={patient!.id}
              syncOffset={dailyOffset}
              syncLatestDay={glucoseLatestDay}
              onDataPresence={handleInsulinPresence}
            />
            <CarboDailyChart
              key="carbo"
              patientId={patient!.id}
              syncOffset={dailyOffset}
              syncLatestDay={glucoseLatestDay}
              onDataPresence={handleCarboPresence}
            />
          </div>
        </>
      )}

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
