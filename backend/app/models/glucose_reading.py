"""Glucose reading model."""
from datetime import datetime
from app import db


class GlucoseReading(db.Model):
    """Represents a single continuous glucose monitor (CGM) reading."""
    __tablename__ = "glucose_readings"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(
        db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True
    )
    timestamp = db.Column(db.DateTime, nullable=False, index=True)
    glucose_mmoll = db.Column(db.Float, nullable=False)  # stored in mmol/L
    source = db.Column(
        db.String(20), nullable=False, default="simulated"
    )  # simulated, dexcom, libre
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Index for efficient time-range queries per patient
    __table_args__ = (
        db.Index("ix_glucose_patient_time", "patient_id", "timestamp"),
    )

    @property
    def status(self) -> str:
        """Classify glucose level into clinical ranges (mmol/L thresholds)."""
        if self.glucose_mmoll < 3.0:
            return "very_low"
        elif self.glucose_mmoll < 3.9:
            return "low"
        elif self.glucose_mmoll <= 10.0:
            return "in_range"
        elif self.glucose_mmoll <= 13.9:
            return "high"
        else:
            return "very_high"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "timestamp": self.timestamp.isoformat(),
            "glucose_mmoll": self.glucose_mmoll,
            "source": self.source,
            "status": self.status,
        }

    def __repr__(self) -> str:
        return f"<GlucoseReading {self.timestamp}: {self.glucose_mmoll} mmol/L>"
