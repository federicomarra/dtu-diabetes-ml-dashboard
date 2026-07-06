"use client";

import { AlertTriangle, CheckCircle, X } from "lucide-react";
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

export default function AnomalyAlert({
  anomalies,
  onAcknowledge,
}: AnomalyAlertProps) {
  const { minSeverity } = useSeverityInference();

  // Apply severity threshold client-side — the slider never triggers a refetch.
  const visible = anomalies.filter(
    (a) => !a.is_acknowledged && (a.severity == null || a.severity >= minSeverity)
  );

  if (visible.length === 0) {
    return (
      <div className={styles.noAlerts}>
        <CheckCircle size={18} />
        <span>No active anomalies</span>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <h3 className={styles.title}>
        <AlertTriangle size={18} />
        Active Alerts ({visible.length})
      </h3>
      <div className={styles.list}>
        {visible.map((anomaly) => (
          <div key={anomaly.id} className={styles.alert}>
            <div className={styles.alertContent}>
              <span className={styles.alertType}>
                {TYPE_LABELS[anomaly.anomaly_type] || anomaly.anomaly_type}
                {anomaly.severity != null && (
                  <strong className={styles.severity}>
                    {" "}{anomaly.severity.toFixed(1)}σ
                  </strong>
                )}
              </span>
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
            {onAcknowledge && (
              <button
                className={styles.ackButton}
                onClick={() => onAcknowledge(anomaly.id)}
                title="Acknowledge"
              >
                <X size={16} />
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
