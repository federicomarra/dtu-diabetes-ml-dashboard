"use client";

import { AlertTriangle, CheckCircle, X } from "lucide-react";
import { format } from "date-fns";
import type { AnomalyDetection } from "@/types";
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
  const unacknowledged = anomalies.filter((a) => !a.is_acknowledged);

  if (unacknowledged.length === 0) {
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
        Active Alerts ({unacknowledged.length})
      </h3>
      <div className={styles.list}>
        {unacknowledged.map((anomaly) => (
          <div key={anomaly.id} className={styles.alert}>
            <div className={styles.alertContent}>
              <span className={styles.alertType}>
                {TYPE_LABELS[anomaly.anomaly_type] || anomaly.anomaly_type}
              </span>
              <span className={styles.alertTime}>
                {format(new Date(anomaly.detected_at), "MMM d, HH:mm")}
              </span>
              <span className={styles.confidence}>
                {Math.round(anomaly.confidence * 100)}% confidence
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
