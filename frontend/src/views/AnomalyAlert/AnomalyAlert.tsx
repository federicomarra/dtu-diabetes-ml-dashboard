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
} from "lucide-react";
import { format } from "date-fns";
import type { AnomalyDetection } from "@/models/types";
import { useSeverityInference } from "@/controllers/SeverityInferenceContext";
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

type SortKey = "severity" | "date";
type SortDir = "asc" | "desc";

export default function AnomalyAlert({
  anomalies,
  onAcknowledge,
}: AnomalyAlertProps) {
  const { minSeverity } = useSeverityInference();
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

  function toggleSort(key: SortKey) {
    if (key === "severity") {
      if (sortKey === "severity") {
        if (sortDir === "desc") {
          setSortDir("asc");
        } else {
          // Clear back to default (date desc)
          setSortKey("date");
          setSortDir("desc");
        }
      } else {
        setSortKey("severity");
        setSortDir("desc");
      }
    } else { // key === "date"
      if (sortKey === "date") {
        if (sortDir === "desc") {
          setSortDir("asc");
        } else {
          setSortDir("desc");
        }
      } else {
        setSortKey("date");
        setSortDir("desc");
      }
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
                  ? "Sorted: highest first — click for lowest first"
                  : "Sorted: lowest first — click to clear"
                : "Sort by severity"
            }
          >
            {getSortIcon("severity")}
            Severity
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

      <div ref={gridRef} className={styles.grid}>
        {visibleCards.map((anomaly) => (
          <div
            key={anomaly.id}
            className={`${styles.card}${anomaly.is_acknowledged ? ` ${styles.cardAcknowledged}` : ""}`}
          >
            <div className={styles.cardHeader}>
              <span className={styles.alertType}>
                {TYPE_LABELS[anomaly.anomaly_type] ?? anomaly.anomaly_type}
              </span>
              <div className={styles.cardHeaderRight}>
                {anomaly.severity != null && (
                  <strong className={styles.severity}>
                    {anomaly.severity.toFixed(1)}σ
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
              {/* confidence is a magnitude bar (rarity), NOT a probability — label it honestly */}
              <span className={styles.confidence}>
                {Math.round(anomaly.confidence * 100)}% strength
              </span>
              {anomaly.description && (
                <p className={styles.description}>{anomaly.description}</p>
              )}
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
