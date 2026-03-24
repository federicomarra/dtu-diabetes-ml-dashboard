"""Anomaly detection business logic."""
from datetime import datetime, timedelta
from typing import Optional
from app import db
from app.models.glucose_reading import GlucoseReading
from app.models.insulin_event import InsulinEvent
from app.models.anomaly_detection import AnomalyDetection


class AnomalyService:
    """Service for rule-based anomaly detection.

    This provides a baseline rule-based detector.
    ML-based detection (LSTM, Isolation Forest, etc.) will be added
    in Phase 3 (w16-25) via the ml/ module.
    """

    # Thresholds for rule-based detection
    HIGH_GLUCOSE_THRESHOLD = 250  # mg/dL
    SUSTAINED_DURATION_MINUTES = 60
    BOLUS_LOOKBACK_MINUTES = 30

    @staticmethod
    def detect_missed_bolus(
        patient_id: int,
        window_start: Optional[datetime] = None,
        window_end: Optional[datetime] = None,
    ) -> list[dict]:
        """Detect potential missed boluses using rule-based heuristics.

        A missed bolus is flagged when glucose stays above the threshold
        for a sustained period without a preceding bolus event.
        """
        if window_end is None:
            window_end = datetime.utcnow()
        if window_start is None:
            window_start = window_end - timedelta(hours=24)

        # Get high glucose readings in the window
        high_readings = (
            GlucoseReading.query
            .filter_by(patient_id=patient_id)
            .filter(GlucoseReading.timestamp.between(window_start, window_end))
            .filter(GlucoseReading.glucose_mgdl >= AnomalyService.HIGH_GLUCOSE_THRESHOLD)
            .order_by(GlucoseReading.timestamp)
            .all()
        )

        if not high_readings:
            return []

        anomalies = []

        for reading in high_readings:
            # Check if there was a bolus within the lookback window
            lookback_start = reading.timestamp - timedelta(
                minutes=AnomalyService.BOLUS_LOOKBACK_MINUTES
            )
            recent_bolus = (
                InsulinEvent.query
                .filter_by(patient_id=patient_id, event_type="bolus")
                .filter(
                    InsulinEvent.timestamp.between(lookback_start, reading.timestamp)
                )
                .first()
            )

            if not recent_bolus:
                anomalies.append({
                    "glucose_reading_id": reading.id,
                    "anomaly_type": "missed_bolus",
                    "confidence": 0.7,
                    "description": (
                        f"Glucose at {reading.glucose_mgdl} mg/dL with no bolus "
                        f"in the preceding {AnomalyService.BOLUS_LOOKBACK_MINUTES} min"
                    ),
                })

        return anomalies

    @staticmethod
    def run_detection_and_store(patient_id: int) -> int:
        """Run all detection rules and store results in the database.

        Returns the number of new anomalies detected.
        """
        detected = AnomalyService.detect_missed_bolus(patient_id)

        for anomaly_data in detected:
            anomaly = AnomalyDetection(
                patient_id=patient_id,
                glucose_reading_id=anomaly_data["glucose_reading_id"],
                anomaly_type=anomaly_data["anomaly_type"],
                confidence=anomaly_data["confidence"],
                description=anomaly_data["description"],
            )
            db.session.add(anomaly)

        db.session.commit()
        return len(detected)
