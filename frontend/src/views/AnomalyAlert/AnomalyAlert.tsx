"use client";

import { useState, useEffect, useRef } from "react";
import {
  AlertTriangle,
  CheckCircle,
  Eye,
  EyeOff,
  ArrowUpDown,
  ArrowDown,
  ArrowUp,
  HelpCircle,
} from "lucide-react";
import { format } from "date-fns";
import type { AnomalyDetection } from "@/models/types";
import { useSeverityInference } from "@/controllers/SeverityInferenceContext";
import { useGlucoseUnit } from "@/controllers/GlucoseUnitContext";
import { describeAnomaly, excursionSize } from "@/models/glucoseUnits";
import styles from "./AnomalyAlert.module.css";

interface AnomalyAlertProps {
  anomalies: AnomalyDetection[];
  onAcknowledge?: (anomalyId: number) => void;
}

const TYPE_LABELS: Record<string, string> = {
  missed_bolus: "Missed Bolus",
  late_bolus: "Late Bolus",
  unusual_pattern: "Unusual Pattern",
};

type SortKey = "severity" | "excursion" | "date";
type SortDir = "asc" | "desc";

// Why the two sorts disagree, in one hover. The card shows a rank (ordinal, honest) rather
// than the raw σ, because σ here is a robust z-score of a heavy-tailed surprise statistic
// and reads as a rarity guarantee it cannot make. See ml/docs/DETECTION_SEVERITY.md §1.
//
// The divergence between this and excursion size is DURATION, not the NLL's uncertainty
// weighting: measured on 3,830 windows, the standardized-error term explains 93.3% of the
// score's variance and the log-variance term only 1.8%. Severity takes an event's single
// worst 160-min window, so spearman(severity, duration) = 0.06 — duration never accumulates.
const SURPRISE_HELP =
  "Surprise score. Each 160-minute window is scored by how far glucose strayed from what " +
  "the model forecast from the insulin and carbs on board, measured against the model's own " +
  "error bar. An event takes its single worst window, so a longer event is not automatically " +
  "more surprising, duration is not added up here. Sort by Excursion to rank by total excess " +
  "glucose instead.";

export default function AnomalyAlert({
  anomalies,
  onAcknowledge,
}: AnomalyAlertProps) {
  const { minSeverity } = useSeverityInference();
  const { unit } = useGlucoseUnit();
  const [sortKey, setSortKey] = useState<SortKey | null>("date");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [showAcknowledged, setShowAcknowledged] = useState(true);
  const [isExpanded, setIsExpanded] = useState(false);
  const [columns, setColumns] = useState(3); // Default fallback column count
  const gridRef = useRef<HTMLDivElement>(null);

  // Measure container width and compute actual grid columns to exactly match '2 rows of cards'
  useEffect(() => {
    if (!gridRef.current) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const width = entry.contentRect.width;
        // Calculation matching CSS: minmax(220px, 1fr) with a gap of 0.75rem (12px)
        // columns * 220 + (columns - 1) * 12 <= width
        // 232 * columns <= width + 12
        const computedCols = Math.max(1, Math.floor((width + 12) / 232));
        setColumns(computedCols);
      }
    });
    observer.observe(gridRef.current);
    return () => observer.disconnect();
  }, []);

  // Surprise rank, assigned over EVERY stored anomaly before any filtering, so a card keeps
  // the same rank as the slider moves. Because the slider also thresholds on severity, the
  // visible ranks stay contiguous (1..N) — a gap only appears when a card is acknowledged
  // away, which correctly signals "that one was handled".
  const rankById = new Map<number, number>(
    [...anomalies]
      .sort((a, b) => (b.severity ?? 0) - (a.severity ?? 0))
      .map((a, i) => [a.id, i + 1])
  );

  // Apply severity threshold client-side — the slider never triggers a refetch.
  const filtered = anomalies.filter(
    (a) =>
      (a.severity == null || a.severity >= minSeverity) &&
      (showAcknowledged || !a.is_acknowledged)
  );

  // Sort: default to date descending
  const sorted = [...filtered].sort((a, b) => {
    if (sortKey === "severity") {
      const sa = a.severity ?? 0;
      const sb = b.severity ?? 0;
      return sortDir === "desc" ? sb - sa : sa - sb;
    }
    if (sortKey === "excursion") {
      // Area over the forecast, NOT the peak deviation — the question "which of these cost
      // the patient the most excess glucose" is different from "which surprised the model
      // most", and the two orders really do differ. Ties fall back to surprise.
      const ea = excursionSize(a.residual_mmoll, a.duration_min);
      const eb = excursionSize(b.residual_mmoll, b.duration_min);
      if (ea !== eb) return sortDir === "desc" ? eb - ea : ea - eb;
      return (b.severity ?? 0) - (a.severity ?? 0);
    }
    if (sortKey === "date") {
      const da = a.detected_at ? new Date(a.detected_at).getTime() : 0;
      const db = b.detected_at ? new Date(b.detected_at).getTime() : 0;
      return sortDir === "desc" ? db - da : da - db;
    }
    // Default fallback (though sortKey starts at "date")
    if (a.is_acknowledged !== b.is_acknowledged) {
      return a.is_acknowledged ? 1 : -1;
    }
    return 0;
  });

  const activeCount = sorted.filter((a) => !a.is_acknowledged).length;

  // Slicing: limit to 2 rows dynamically unless expanded
  const limit = isExpanded ? sorted.length : 2 * columns;
  const visibleCards = sorted.slice(0, limit);
  const hasMoreThanTwoRows = sorted.length > 2 * columns;

  // First click sorts descending; second flips to ascending; a third on a non-default key
  // returns to the default (date desc). Date itself just cycles direction.
  function toggleSort(key: SortKey) {
    if (sortKey !== key) {
      setSortKey(key);
      setSortDir("desc");
      return;
    }
    if (sortDir === "desc") {
      setSortDir("asc");
      return;
    }
    if (key === "date") {
      setSortDir("desc");
    } else {
      setSortKey("date");
      setSortDir("desc");
    }
  }

  function getSortIcon(key: SortKey) {
    if (sortKey !== key) return <ArrowUpDown size={13} />;
    return sortDir === "desc" ? <ArrowDown size={13} /> : <ArrowUp size={13} />;
  }

  if (sorted.length === 0) {
    return (
      <div className={styles.noAlerts}>
        <CheckCircle size={18} />
        <span>No active anomalies</span>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h3 className={styles.title}>
          <AlertTriangle size={17} />
          Active Alerts
          <span className={styles.badge}>{activeCount}</span>
        </h3>
        <div className={styles.sortButtons}>
          <button
            className={`${styles.sortBtn}${sortKey === "severity" ? ` ${styles.sortBtnActive}` : ""}`}
            onClick={() => toggleSort("severity")}
            title={
              sortKey === "severity"
                ? sortDir === "desc"
                  ? "Sorted: most unexpected first — click to reverse"
                  : "Sorted: least unexpected first — click to clear"
                : "Sort by how unexpected the event was"
            }
          >
            {getSortIcon("severity")}
            Surprise
          </button>
          <button
            className={`${styles.sortBtn}${sortKey === "excursion" ? ` ${styles.sortBtnActive}` : ""}`}
            onClick={() => toggleSort("excursion")}
            title={
              sortKey === "excursion"
                ? sortDir === "desc"
                  ? "Sorted: largest excursion first — click to reverse"
                  : "Sorted: smallest excursion first — click to clear"
                : "Sort by excursion size — total excess glucose above forecast (deviation × duration)"
            }
          >
            {getSortIcon("excursion")}
            Excursion
          </button>
          <button
            className={`${styles.sortBtn}${sortKey === "date" ? ` ${styles.sortBtnActive}` : ""}`}
            onClick={() => toggleSort("date")}
            title={
              sortKey === "date"
                ? sortDir === "desc"
                  ? "Sorted: newest first — click for oldest first"
                  : "Sorted: oldest first — click to clear"
                : "Sort by date"
            }
          >
            {getSortIcon("date")}
            Date
          </button>
          <button
            className={`${styles.sortBtn}${showAcknowledged ? ` ${styles.sortBtnActive}` : ""}`}
            onClick={() => setShowAcknowledged(!showAcknowledged)}
            title={
              showAcknowledged
                ? "Hide acknowledged anomalies"
                : "Show acknowledged anomalies"
            }
          >
            {showAcknowledged ? <Eye size={13} /> : <EyeOff size={13} />}
            Show Acknowledged
          </button>
        </div>
      </div>

      {/* Stated once for the list, not repeated on 31 cards. The tooltip on each score
          carries the maths; this carries the takeaway, and is visible without hovering —
          which matters on touch, and to anyone watching a demo over your shoulder. */}
      <p className={styles.rankNote}>
        Ranked <strong>#1</strong> onwards by how <em>unexpected</em> each event was, given the
        insulin and carbs on board. This takes each event&apos;s single worst window, so a longer
        event is not automatically higher. Sort by <em>Excursion</em> to rank by total excess
        glucose instead.
      </p>

      <div ref={gridRef} className={styles.grid}>
        {visibleCards.map((anomaly) => (
          <div
            key={anomaly.id}
            className={`${styles.card}${anomaly.is_acknowledged ? ` ${styles.cardAcknowledged}` : ""}`}
          >
            <div className={styles.cardHeader}>
              <span className={styles.alertType}>
                <span className={styles.rank} title="Surprise rank across every anomaly in this window">
                  #{rankById.get(anomaly.id)}
                </span>
                {TYPE_LABELS[anomaly.anomaly_type] ?? anomaly.anomaly_type}
              </span>
              <div className={styles.cardHeaderRight}>
                {anomaly.severity != null && (
                  <strong className={styles.severity} title={SURPRISE_HELP}>
                    {anomaly.severity.toFixed(1)}
                    <HelpCircle size={11} aria-hidden="true" />
                  </strong>
                )}
                {onAcknowledge && !anomaly.is_acknowledged && (
                  <button
                    className={styles.ackButton}
                    onClick={() => onAcknowledge(anomaly.id)}
                    title="Mark as seen"
                  >
                    <Eye size={14} />
                  </button>
                )}
              </div>
            </div>

            <div className={styles.cardBody}>
              {anomaly.detected_at && (
                <span className={styles.alertTime} suppressHydrationWarning>
                  {format(new Date(anomaly.detected_at), "MMM d, HH:mm")}
                </span>
              )}
              {/* `confidence` (0-100 "strength") is gone: it was 100 × severity / max severity
                  in the response, a linear rescale of the surprise score whose ordering was
                  identical (Spearman 1.0). It carried nothing the rank and score do not.

                  Excursion size (|residual| × duration) is NOT rendered either. It drives the
                  Excursion sort, but as a display value "426 mmol/L·min" is an invented unit a
                  patient cannot act on — and the sentence below already gives both factors
                  ("6.6 mmol/L above forecast for 65 min"), from which it is the product. */}
              {(() => {
                // Composed here, not on the server: `description` is fixed to mmol/L.
                const text = describeAnomaly(
                  anomaly.residual_mmoll,
                  anomaly.duration_min,
                  anomaly.anomaly_type,
                  unit,
                  anomaly.description
                );
                return text ? <p className={styles.description}>{text}</p> : null;
              })()}
            </div>
          </div>
        ))}
      </div>

      {hasMoreThanTwoRows && (
        <div className={styles.expandCollapseContainer}>
          <button
            className={styles.expandCollapseBtn}
            onClick={() => setIsExpanded(!isExpanded)}
          >
            {isExpanded ? "Show Less" : "Show More"}
          </button>
        </div>
      )}
    </div>
  );
}
