"use client";

import Link from "next/link";
import { ChevronLeft, ChevronRight } from "lucide-react";
import PatientOverview from "@/views/PatientOverview/PatientOverview";
import {
  useDoctorController,
  PER_PAGE_OPTIONS,
  type PerPageOption,
} from "@/controllers/useDoctorController";
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
  } = useDoctorController();

  /** Per-page selector is shown whenever the total exceeds the minimum option (20). */
  const showPerPageSelector = totalPatients > PER_PAGE_OPTIONS[0];

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
          <h2 className={styles.pageTitle}>Doctor Dashboard</h2>
          <p className={styles.subtitle}>
            {totalPatients} patients • {totalAlerts} total alerts
            {totalPages > 1 && (
              <> — page {page} of {totalPages}</>
            )}
          </p>
        </div>

        {/* Per-page selector */}
        {showPerPageSelector && (
          <div className={styles.toolbar}>
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
        {patients.map(({ patient, latestReading, tir, anomalyCount, averageGlucose }) => (
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
