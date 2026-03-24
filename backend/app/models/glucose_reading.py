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
    glucose_mgdl = db.Column(db.Float, nullable=False)
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
        """Classify glucose level into clinical ranges."""
        if self.glucose_mgdl < 54:
            return "very_low"
        elif self.glucose_mgdl < 70:
            return "low"
        elif self.glucose_mgdl <= 180:
            return "in_range"
        elif self.glucose_mgdl <= 250:
            return "high"
        else:
            return "very_high"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "timestamp": self.timestamp.isoformat(),
            "glucose_mgdl": self.glucose_mgdl,
            "source": self.source,
            "status": self.status,
        }

    def __repr__(self) -> str:
        return f"<GlucoseReading {self.timestamp}: {self.glucose_mgdl} mg/dL>"
