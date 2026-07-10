"use client";

import { useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Sparkles, Loader2 } from "lucide-react";
import GlucoseDailyChart from "@/views/GlucoseDailyChart/GlucoseDailyChart";
import TIRChart, { RangesModal } from "@/views/TIRChart/TIRChart";
import PatientOverview from "@/views/PatientOverview/PatientOverview";
import AnomalyAlert from "@/views/AnomalyAlert/AnomalyAlert";
import MultiWeeklyChart from "@/views/MultiWeeklyChart/MultiWeeklyChart";
import InsulinDailyChart from "@/views/InsulinDailyChart/InsulinDailyChart";
import CarboDailyChart from "@/views/CarboDailyChart/CarboDailyChart";
import GlucoseScatterplot from "@/views/GlucoseScatterplot/GlucoseScatterplot";
import DataUploader from "@/views/DataUploader/DataUploader";
import { clearSession } from "@/models/session";
import { usePatientDetailController } from "@/controllers/usePatientDetailController";
import { useTimeRange, useTimeRangeSelector } from "@/controllers/TimeRangeContext";
import { useGlucoseRanges } from "@/controllers/GlucoseRangesContext";
import {
  useSeverityInference,
  SEVERITY_MIN,
  SEVERITY_MAX,
  SEVERITY_STEP,
} from "@/controllers/SeverityInferenceContext";
import { useGlucoseUnit } from "@/controllers/GlucoseUnitContext";
import styles from "./PatientDetailView.module.css";

interface PatientDetailViewProps {
  mode: "doctor" | "patient";
}

export default function PatientDetailView({ mode }: PatientDetailViewProps) {
  const { ext_id } = useParams<{ ext_id: string }>();
  const router = useRouter();
  const ctrl = usePatientDetailController(ext_id);
  const { timeRange } = useTimeRange();
  const { ranges: glucoseRanges, setRanges: onThresholdsChange } = useGlucoseRanges();
  const { inferenceEnabled, setInferenceEnabled, minSeverity, setMinSeverity } = useSeverityInference();
  const sliderPct = ((minSeverity - SEVERITY_MIN) / (SEVERITY_MAX - SEVERITY_MIN)) * 100;
  const { unit } = useGlucoseUnit();
  const [showRangesModal, setShowRangesModal] = useState(false);

  // Shared daily-view state — GlucoseDailyChart is the source of truth
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

  const {
    activeVal,
    activeUnit,
    valuesArray,
    handleUnitChange,
    handleValueChange,
  } = useTimeRangeSelector();

  if (ctrl.loading) {
    return (
      <div className={styles.dashboard}>
        {mode === "doctor" && (
          <Link href="/doctor" className={styles.backLink}>
            <ArrowLeft size={16} /> Back to Doctor Dashboard
          </Link>
        )}
        <p style={{ color: "var(--text-secondary)", marginTop: "2rem" }}>
          {mode === "doctor" ? "Loading patient data…" : "Loading dashboard data…"}
        </p>
      </div>
    );
  }

  if (ctrl.notFound) {
    if (mode === "doctor") {
      return (
        <div className={styles.notFound}>
          <p>
            Patient <code>{ext_id}</code> not found.
          </p>
          <Link href="/doctor" className={styles.backLink}>
            <ArrowLeft size={16} /> Back to Doctor Dashboard
          </Link>
        </div>
      );
    } else {
      return (
        <div className={styles.dashboard} style={{ textAlign: "center", padding: "4rem 2rem" }}>
          <h2 style={{ color: "var(--color-high)", marginBottom: "1rem" }}>Patient Not Found</h2>
          <p style={{ color: "var(--text-secondary)", marginBottom: "2rem" }}>
            We couldn&apos;t find a patient with ID: <code>{ext_id}</code>.
          </p>
          <button
            onClick={() => {
              // Drop the saved session first: it is what sent us to this missing patient,
              // and /patient would bounce straight back here if we left it in place.
              clearSession();
              router.push("/patient");
            }}
            style={{
              background: "var(--primary)",
              color: "white",
              border: "none",
              padding: "0.75rem 1.5rem",
              borderRadius: "8px",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Go to Patient Login
          </button>
        </div>
      );
    }
  }

  if (ctrl.error) {
    return (
      <div className={styles.dashboard}>
        {mode === "doctor" && (
          <Link href="/doctor" className={styles.backLink}>
            <ArrowLeft size={16} /> Back to Doctor Dashboard
          </Link>
        )}
        <p style={{ color: "var(--color-high)", marginTop: "2rem" }}>
          Error: {ctrl.error}
        </p>
      </div>
    );
  }

  const {
    patient,
    tir,
    readings,
    multiWeekReadings,
    anomalies,
    latestReading,
    averageGlucose,
    hba1c,
    gmi,
    scatterplotData,
    handleAcknowledge,
  } = ctrl;

  const allChartsPresent = hasInsulin && hasCarbo;
  const onlyOneChart = (hasInsulin || hasCarbo) && !allChartsPresent;

  const anomalyCount = mode === "doctor"
    ? anomalies.filter((a) => !a.is_acknowledged && (a.severity == null || a.severity >= minSeverity)).length
    : anomalies.filter((a) => !a.is_acknowledged).length;

  // What the slider actually buys, in the two units a reader can act on: how many events
  // survive the threshold, and how many that is per day. AnomalyAlert applies the same filter.
  const shownAnomalies = anomalies.filter(
    (a) => a.severity == null || a.severity >= minSeverity
  ).length;

  const anomalyRatePerDay = (() => {
    const stamps = anomalies
      .map((a) => (a.detected_at ? new Date(a.detected_at).getTime() : NaN))
      .filter((t) => !Number.isNaN(t));
    if (stamps.length < 2) return null;
    const days = (Math.max(...stamps) - Math.min(...stamps)) / 86_400_000;
    if (days < 0.5) return null;
    return (shownAnomalies / days).toFixed(1);
  })();

  return (
    <div className={styles.dashboard}>
      {mode === "doctor" && (
        <Link href="/doctor" className={styles.backLink}>
          <ArrowLeft size={16} />
          Back to Doctor Dashboard
        </Link>
      )}

      <div className={styles.titleRow}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
        {mode === "doctor" ? (
          <h2 className={styles.pageTitle}>Patient Detail View</h2>
        ) : (
          <h2 className={styles.pageTitle}>Patient Dashboard</h2>
        )}
          {ctrl.isRefreshing && (
            <span style={{
              fontSize: "0.8rem",
              fontWeight: 500,
              color: "var(--text-secondary)",
              background: "var(--border)",
              padding: "0.25rem 0.6rem",
              borderRadius: "6px",
              display: "inline-flex",
              alignItems: "center",
              gap: "0.4rem",
            }}>
              <span style={{
                display: "inline-block",
                width: "6px",
                height: "6px",
                borderRadius: "50%",
                background: "var(--primary)",
              }} />
              Updating...
            </span>
          )}
        </div>

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

          {/* Anomaly detection: toggle inference for the current window + sensitivity filter */}
          <div className={styles.switchContainer} title="Run ML anomaly detection over the selected window">
            <span className={styles.switchLabel}>
              {ctrl.isRefreshing && inferenceEnabled ? (
                <Loader2 size={13} className={styles.spinner} />
              ) : (
                    <Sparkles size={13} className={inferenceEnabled ? styles.sparkleActive : ""} />
              )}
                  ML Anomaly Detection
            </span>
                <button
                  type="button"
                  id="ml-detection-toggle"
                  className={`${styles.switchTrack} ${inferenceEnabled ? styles.switchTrackActive : ""}`}
                  onClick={() => setInferenceEnabled(!inferenceEnabled)}
                  aria-checked={inferenceEnabled}
                  role="switch"
                >
                  <span className={`${styles.switchKnob} ${inferenceEnabled ? styles.switchKnobActive : ""}`} />
                </button>
              </div>

              <div className={styles.sliderContainer}>
                <label htmlFor="sensitivity" className={styles.sliderLabel}>Sensitivity</label>
                <input
                  id="sensitivity"
                  type="range"
                  min={SEVERITY_MIN}
                  max={SEVERITY_MAX}
                  step={SEVERITY_STEP}
                  value={minSeverity}
                  onChange={(e) => setMinSeverity(Number(e.target.value))}
                  aria-describedby="sensitivity-readout"
                  className={styles.sliderInput}
                  style={{ "--pct": `${sliderPct}%` } as React.CSSProperties}
                />
                <span className={styles.sliderValue}>{shownAnomalies}</span>
              </div>
              {/* The threshold is a review-workload dial, not a rarity statistic: the score
                  distribution is heavy-tailed (skew ~7), so "6σ" is a 1-in-27 window, not a
                  1-in-a-billion one. State the workload, which is the only promise it keeps. */}
              <p id="sensitivity-readout" className={styles.sliderReadout}>
                Showing <strong>{shownAnomalies}</strong> of {anomalies.length} detected
                {anomalyRatePerDay != null && <> · ~{anomalyRatePerDay} per day</>}, ranked by
                how far glucose strayed from its forecast.
              </p>
        </div>
      </div>

      <PatientOverview
        patientName={patient!.name}
        patientId={patient!.external_id}
        patientAge={patient!.age != null ? String(patient!.age) : "??"}
        latestReading={latestReading}
        tir={tir ?? undefined}
        anomalyCount={anomalyCount}
        averageGlucose={averageGlucose}
        timeRangeLast={timeRange.last}
        hba1c={hba1c ?? undefined}
        gmi={gmi ?? undefined}
        isDetailView={true}
      />

      {mode === "patient" && (
        <DataUploader patientId={patient!.id} allowedTypes={["csv", "zip"]} onUploadSuccess={ctrl.refresh} />
      )}

      {anomalies.length > 0 && (
        <AnomalyAlert anomalies={anomalies} onAcknowledge={handleAcknowledge} />
      )}

      {/* Row 1: Glucose + TIR side-by-side when both charts present, else glucose full width */}
      <div className={allChartsPresent ? styles.chartsGrid : styles.chartsGridFull}>
        <GlucoseDailyChart
          key={`glucose-${ctrl.refreshKey}`}
          readings={readings}
          patientId={patient!.id}
          anomalies={anomalies}
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
            key={`insulin-${ctrl.refreshKey}`}
            patientId={patient!.id}
            syncOffset={dailyOffset}
            syncLatestDay={glucoseLatestDay}
            onDataPresence={handleInsulinPresence}
          />
          <CarboDailyChart
            key={`carbo-${ctrl.refreshKey}`}
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
              key={`insulin-${ctrl.refreshKey}`}
              patientId={patient!.id}
              syncOffset={dailyOffset}
              syncLatestDay={glucoseLatestDay}
              onDataPresence={handleInsulinPresence}
            />
          )}
          {hasCarbo && (
            <CarboDailyChart
              key={`carbo-${ctrl.refreshKey}`}
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
              key={`insulin-${ctrl.refreshKey}`}
              patientId={patient!.id}
              syncOffset={dailyOffset}
              syncLatestDay={glucoseLatestDay}
              onDataPresence={handleInsulinPresence}
            />
            <CarboDailyChart
              key={`carbo-${ctrl.refreshKey}`}
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
