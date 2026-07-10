"use client";

import Link from "next/link";
import { ChevronLeft, ChevronRight, ArrowUpDown, ArrowDown, ArrowUp } from "lucide-react";
import PatientOverview from "@/views/PatientOverview/PatientOverview";
import DataUploader from "@/views/DataUploader/DataUploader";
import {
  useDoctorController,
  PER_PAGE_OPTIONS,
  type PerPageOption,
} from "@/controllers/useDoctorController";
import { useTimeRangeSelector } from "@/controllers/TimeRangeContext";
import styles from "./doctor.module.css";


/**
 * Doctor Dashboard — thin shell.
 * All data and business logic lives in useDoctorController.
 */
export default function DoctorDashboard() {
  const {
    patients,
    totalPatients,
    totalAlerts,
    loading,
    error,
    page,
    perPage,
    totalPages,
    setPage,
    setPerPage,
    refresh,
    isRefreshing,
    sortKey,
    sortDir,
    toggleSort,
  } = useDoctorController();

  const {
    activeVal,
    activeUnit,
    valuesArray,
    handleUnitChange,
    handleValueChange,
  } = useTimeRangeSelector();

  /** Per-page selector is shown whenever the total exceeds the minimum option (20). */
  const showPerPageSelector = totalPatients > PER_PAGE_OPTIONS[0];

  function getSortIcon(key: "name" | "ext_id" | "age" | "anomalies" | "tir") {
    if (sortKey !== key) return <ArrowUpDown size={13} />;
    return sortDir === "desc" ? <ArrowDown size={13} /> : <ArrowUp size={13} />;
  }

  if (loading) {
    return (
      <div className={styles.dashboard}>
        <div className={styles.header}>
          <h2 className={styles.pageTitle}>Doctor Dashboard</h2>
          <p className={styles.subtitle}>Loading patients…</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className={styles.dashboard}>
        <div className={styles.header}>
          <h2 className={styles.pageTitle}>Doctor Dashboard</h2>
          <p className={styles.subtitle} style={{ color: "var(--color-high)" }}>
            Error: {error}
          </p>
        </div>
      </div>
    );
  }

  /* Build a compact list of page numbers to show around the current page */
  const pageNumbers: (number | "…")[] = [];
  if (totalPages <= 7) {
    for (let i = 1; i <= totalPages; i++) pageNumbers.push(i);
  } else {
    const left = Math.max(2, page - 1);
    const right = Math.min(totalPages - 1, page + 1);
    pageNumbers.push(1);
    if (left > 2) pageNumbers.push("…");
    for (let i = left; i <= right; i++) pageNumbers.push(i);
    if (right < totalPages - 1) pageNumbers.push("…");
    pageNumbers.push(totalPages);
  }

  return (
    <div className={styles.dashboard}>
      {/* ── Header ───────────────────────────────────────── */}
      <div className={styles.header}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
            <h2 className={styles.pageTitle}>Doctor Dashboard</h2>
            {isRefreshing && (
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
          <p className={styles.subtitle}>
            {totalPatients} patients • {totalAlerts} total alerts
            {totalPages > 1 && (
              <> — page {page} of {totalPages}</>
            )}
          </p>
        </div>

        {/* Toolbar containing sorting buttons and per-page selector */}
        <div className={styles.toolbar}>
          {/* Sorting controls */}
          <div className={styles.sortButtons}>
            <span className={styles.toolbarLabel}>Sort by</span>
            <button
              className={`${styles.sortBtn}${sortKey === "name" ? ` ${styles.sortBtnActive}` : ""}`}
              onClick={() => toggleSort("name")}
              title={
                sortKey === "name"
                  ? sortDir === "asc"
                    ? "Sorted: A to Z — click for Z to A"
                    : "Sorted: Z to A — click for A to Z"
                  : "Sort by name"
              }
            >
              {getSortIcon("name")}
              Name
            </button>
            <button
              className={`${styles.sortBtn}${sortKey === "ext_id" ? ` ${styles.sortBtnActive}` : ""}`}
              onClick={() => toggleSort("ext_id")}
              title={
                sortKey === "ext_id"
                  ? sortDir === "asc"
                    ? "Sorted: ID low to high — click for high to low"
                    : "Sorted: ID high to low — click for low to high"
                  : "Sort by External ID"
              }
            >
              {getSortIcon("ext_id")}
              ID
            </button>
            <button
              className={`${styles.sortBtn}${sortKey === "age" ? ` ${styles.sortBtnActive}` : ""}`}
              onClick={() => toggleSort("age")}
              title={
                sortKey === "age"
                  ? sortDir === "asc"
                    ? "Sorted: youngest first — click for oldest first"
                    : "Sorted: oldest first — click for youngest first"
                  : "Sort by age"
              }
            >
              {getSortIcon("age")}
              Age
            </button>
            <button
              className={`${styles.sortBtn}${sortKey === "anomalies" ? ` ${styles.sortBtnActive}` : ""}`}
              onClick={() => toggleSort("anomalies")}
              title={
                sortKey === "anomalies"
                  ? sortDir === "asc"
                    ? "Sorted: anomalies low to high — click for high to low"
                    : "Sorted: anomalies high to low — click for low to high"
                  : "Sort by anomalies"
              }
            >
              {getSortIcon("anomalies")}
              Anomalies
            </button>
            <button
              className={`${styles.sortBtn}${sortKey === "tir" ? ` ${styles.sortBtnActive}` : ""}`}
              onClick={() => toggleSort("tir")}
              title={
                sortKey === "tir"
                  ? sortDir === "asc"
                    ? "Sorted: TIR low to high — click for high to low"
                    : "Sorted: TIR high to low — click for low to high"
                  : "Sort by Time in Range (TIR)"
              }
            >
              {getSortIcon("tir")}
              TIR
            </button>
          </div>

          {/* Time range selector */}
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

          {/* Per-page selector */}
          {showPerPageSelector && (
            <div className={styles.perPageSelector}>
              <span className={styles.toolbarLabel}>Show</span>
              <div className={styles.perPageGroup}>
                {PER_PAGE_OPTIONS.filter((opt) => opt < totalPatients).map((opt) => (
                  <button
                    key={opt}
                    id={`per-page-${opt}`}
                    className={`${styles.perPageBtn} ${perPage === opt ? styles.perPageBtnActive : ""}`}
                    onClick={() => setPerPage(opt as PerPageOption)}
                  >
                    {opt}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Parquet Data Uploader ─────────────────────────────────── */}
      <div style={{ marginBottom: "0.05rem" }}>
        <DataUploader allowedTypes={["parquet"]} onUploadSuccess={refresh} />
      </div>

      {/* ── Pagination if needed ────────────────────────────── */}
      {totalPatients > perPage && totalPages > 1 && perPage > 50 && (
        <nav className={styles.pagination} aria-label="Patient pages">
          <button
            id="pagination-prev"
            className={styles.pageBtn}
            onClick={() => setPage(page - 1)}
            disabled={page === 1}
            aria-label="Previous page"
          >
            <ChevronLeft size={16} />
          </button>

          {pageNumbers.map((n, idx) =>
            n === "…" ? (
              <span key={`ellipsis-${idx}`} className={styles.ellipsis}>
                …
              </span>
            ) : (
              <button
                key={n}
                id={`pagination-page-${n}`}
                className={`${styles.pageBtn} ${n === page ? styles.pageBtnActive : ""}`}
                onClick={() => setPage(n as number)}
                aria-current={n === page ? "page" : undefined}
              >
                {n}
              </button>
            )
          )}

          <button
            id="pagination-next"
            className={styles.pageBtn}
            onClick={() => setPage(page + 1)}
            disabled={page === totalPages}
            aria-label="Next page"
          >
            <ChevronRight size={16} />
          </button>
        </nav>
      )}

      {/* ── Patient grid ─────────────────────────────────── */}
      <div className={styles.patientsGrid}>
        {patients.map(({ patient, latestReading, tir, anomalyCount, averageGlucose, hba1c }) => (
          <Link
            key={patient.id}
            href={`/doctor/${patient.external_id}`}
            className={styles.cardLink}
          >
            <PatientOverview
              patientName={patient.name}
              patientId={patient.external_id}
              patientAge={patient.age != null ? String(patient.age) : "??"}
              latestReading={latestReading}
              tir={tir ?? undefined}
              anomalyCount={anomalyCount}
              averageGlucose={averageGlucose}
              hba1c={hba1c ?? undefined}
            />
          </Link>
        ))}
      </div>

      {/* ── Pagination ───────────────────────────────────── */}
      {totalPatients > perPage && totalPages > 1 && (
        <nav className={styles.pagination} aria-label="Patient pages">
          <button
            id="pagination-prev"
            className={styles.pageBtn}
            onClick={() => setPage(page - 1)}
            disabled={page === 1}
            aria-label="Previous page"
          >
            <ChevronLeft size={16} />
          </button>

          {pageNumbers.map((n, idx) =>
            n === "…" ? (
              <span key={`ellipsis-${idx}`} className={styles.ellipsis}>
                …
              </span>
            ) : (
              <button
                key={n}
                id={`pagination-page-${n}`}
                className={`${styles.pageBtn} ${n === page ? styles.pageBtnActive : ""}`}
                onClick={() => setPage(n as number)}
                aria-current={n === page ? "page" : undefined}
              >
                {n}
              </button>
            )
          )}

          <button
            id="pagination-next"
            className={styles.pageBtn}
            onClick={() => setPage(page + 1)}
            disabled={page === totalPages}
            aria-label="Next page"
          >
            <ChevronRight size={16} />
          </button>
        </nav>
      )}
    </div>
  );
}
