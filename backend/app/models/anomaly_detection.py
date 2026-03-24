"""Anomaly detection model."""
from datetime import datetime
from app import db


class AnomalyDetection(db.Model):
    """Stores ML-detected anomalies (missed/late boluses, unusual patterns)."""
    __tablename__ = "anomaly_detections"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(
        db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True
    )
    glucose_reading_id = db.Column(
        db.Integer, db.ForeignKey("glucose_readings.id"), nullable=True
    )
    anomaly_type = db.Column(
        db.String(30), nullable=False
    )  # missed_bolus, late_bolus, unusual_pattern
    confidence = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text, nullable=True)
    is_acknowledged = db.Column(db.Boolean, default=False)
    detected_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationship to the triggering glucose reading
    glucose_reading = db.relationship("GlucoseReading", backref="anomalies")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "glucose_reading_id": self.glucose_reading_id,
            "anomaly_type": self.anomaly_type,
            "confidence": self.confidence,
            "description": self.description,
            "is_acknowledged": self.is_acknowledged,
            "detected_at": self.detected_at.isoformat() if self.detected_at else None,
        }

    def __repr__(self) -> str:
        return f"<AnomalyDetection {self.anomaly_type} @ {self.detected_at}>"
