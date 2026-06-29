"use client";

import { useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import GlucoseChart from "@/views/GlucoseChart/GlucoseChart";
import TIRChart, { RangesModal } from "@/views/TIRChart/TIRChart";
import MultiWeeklyChart from "@/views/MultiWeeklyChart/MultiWeeklyChart";
import PatientOverview from "@/views/PatientOverview/PatientOverview";
import AnomalyAlert from "@/views/AnomalyAlert/AnomalyAlert";
import InsulinDailyChart from "@/views/InsulinDailyChart/InsulinDailyChart";
import CarboDailyChart from "@/views/CarboDailyChart/CarboDailyChart";
import GlucoseScatterplot from "@/views/GlucoseScatterplot/GlucoseScatterplot";
import { usePatientDetailController } from "@/controllers/usePatientDetailController";
import { useTimeRange, parseLast } from "@/controllers/TimeRangeContext";
import { useGlucoseRanges } from "@/controllers/GlucoseRangesContext";
import { useGlucoseUnit } from "@/controllers/GlucoseUnitContext";
import { uploadCsv } from "@/models/api";
import styles from "../patient.module.css";

/**
 * Dynamic Patient Dashboard.
 * Loads patient data based on the external_id path segment.
 */
export default function PatientDashboard() {
  const { external_id } = useParams<{ external_id: string }>();
  const router = useRouter();
  const ctrl = usePatientDetailController(external_id);

  const { timeRange, setLast } = useTimeRange();
  const { ranges: glucoseRanges, setRanges: onThresholdsChange } = useGlucoseRanges();
  const { unit } = useGlucoseUnit();
  const [showRangesModal, setShowRangesModal] = useState(false);

  // CSV Upload states
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<{
    success: boolean;
    message: string;
    stats?: { glucose: number; meal: number; insulin: number };
  } | null>(null);

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

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setCsvFile(e.target.files[0]);
      setUploadResult(null);
    }
  };

  const handleCsvUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!csvFile || !ctrl.patient) return;

    setUploading(true);
    setUploadResult(null);

    try {
      const res = await uploadCsv(ctrl.patient.id, csvFile);
      setUploadResult({
        success: true,
        message: res.message,
        stats: {
          glucose: res.glucose_count,
          meal: res.meal_count,
          insulin: res.insulin_count,
        },
      });
      setCsvFile(null);
      // Refresh page data
      setTimeout(() => {
        router.refresh();
      }, 1500);
    } catch (err: any) {
      console.error(err);
      setUploadResult({
        success: false,
        message: err.response?.data?.error || "Failed to upload CSV file",
      });
    } finally {
      setUploading(false);
    }
  };

  if (ctrl.loading) {
    return (
      <div className={styles.dashboard}>
        <p style={{ color: "var(--text-secondary)", marginTop: "2rem" }}>
          Loading dashboard data…
        </p>
      </div>
    );
  }

  if (ctrl.notFound) {
    return (
      <div className={styles.dashboard} style={{ textAlign: "center", padding: "4rem 2rem" }}>
        <h2 style={{ color: "var(--color-high)", marginBottom: "1rem" }}>Patient Not Found</h2>
        <p style={{ color: "var(--text-secondary)", marginBottom: "2rem" }}>
          We couldn't find a patient with ID: <code>{external_id}</code>.
        </p>
        <button
          onClick={() => router.push("/patient")}
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

  if (ctrl.error) {
    return (
      <div className={styles.dashboard}>
        <p style={{ color: "var(--color-high)", marginTop: "2rem" }}>
          Error: {ctrl.error}
        </p>
      </div>
    );
  }

  const { patient, readings, multiWeekReadings, tir, anomalies, latestReading, averageGlucose, hba1c, gmi, scatterplotData, handleAcknowledge } = ctrl;

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
        patientAge={patient!.age != null ? String(patient!.age) : "??"}
        latestReading={latestReading}
        tir={tir ?? undefined}
        anomalyCount={anomalies.filter((a) => !a.is_acknowledged).length}
        averageGlucose={averageGlucose}
        timeRangeLast={timeRange.last}
        hba1c={hba1c ?? undefined}
        gmi={gmi ?? undefined}
      />

      {/* CSV Upload Section */}
      <div style={{
        background: "var(--card-bg)",
        border: "1px solid var(--border)",
        borderRadius: "16px",
        padding: "1.5rem",
        marginBottom: "1.5rem",
        boxShadow: "0 4px 6px -1px rgba(0, 0, 0, 0.05)"
      }}>
        <h3 style={{ fontSize: "1.1rem", fontWeight: 700, marginBottom: "1rem", color: "var(--text-primary)" }}>
          Upload LibreView Data (CSV)
        </h3>
        <form onSubmit={handleCsvUpload} style={{ display: "flex", flexWrap: "wrap", gap: "1rem", alignItems: "center" }}>
          <div style={{ flex: 1, minWidth: "250px" }}>
            <input
              type="file"
              accept=".csv"
              onChange={handleFileChange}
              id="csv-file-input"
              style={{ display: "none" }}
            />
            <label
              htmlFor="csv-file-input"
              style={{
                display: "block",
                padding: "0.75rem 1rem",
                border: "2px dashed var(--border)",
                borderRadius: "8px",
                textAlign: "center",
                cursor: "pointer",
                color: "var(--text-secondary)",
                background: "var(--bg)",
                transition: "all 0.2s"
              }}
              onMouseOver={(e) => (e.currentTarget.style.borderColor = "var(--primary)")}
              onMouseOut={(e) => (e.currentTarget.style.borderColor = "var(--border)")}
            >
              {csvFile ? `Selected: ${csvFile.name}` : "Click to select a LibreView CSV file"}
            </label>
          </div>
          <button
            type="submit"
            disabled={!csvFile || uploading}
            style={{
              background: !csvFile ? "var(--border)" : "var(--primary)",
              color: "white",
              border: "none",
              padding: "0.75rem 1.5rem",
              borderRadius: "8px",
              fontWeight: 600,
              cursor: !csvFile ? "not-allowed" : "pointer",
              transition: "opacity 0.2s"
            }}
          >
            {uploading ? "Importing..." : "Upload & Parse"}
          </button>
        </form>

        {uploadResult && (
          <div style={{
            marginTop: "1rem",
            padding: "0.75rem 1rem",
            borderRadius: "8px",
            fontSize: "0.9rem",
            background: uploadResult.success ? "rgba(39, 174, 96, 0.1)" : "rgba(231, 76, 60, 0.1)",
            border: `1px solid ${uploadResult.success ? "var(--success)" : "var(--danger)"}`,
            color: uploadResult.success ? "var(--success)" : "var(--danger)"
          }}>
            <div style={{ fontWeight: 600, marginBottom: "0.25rem" }}>{uploadResult.message}</div>
            {uploadResult.success && uploadResult.stats && (
              <div style={{ fontSize: "0.85rem", opacity: 0.9 }}>
                Imported: {uploadResult.stats.glucose} glucose readings, {uploadResult.stats.meal} carb entries, {uploadResult.stats.insulin} insulin doses.
              </div>
            )}
          </div>
        )}
      </div>

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
