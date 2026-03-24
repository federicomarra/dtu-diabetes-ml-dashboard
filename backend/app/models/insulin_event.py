"""Insulin event model."""
from datetime import datetime
from app import db


class InsulinEvent(db.Model):
    """Represents an insulin administration event (bolus or basal)."""
    __tablename__ = "insulin_events"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(
        db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True
    )
    timestamp = db.Column(db.DateTime, nullable=False, index=True)
    units = db.Column(db.Float, nullable=False)
    event_type = db.Column(
        db.String(10), nullable=False
    )  # bolus, basal
    is_late = db.Column(db.Boolean, default=False)
    is_missed = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.Index("ix_insulin_patient_time", "patient_id", "timestamp"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "timestamp": self.timestamp.isoformat(),
            "units": self.units,
            "event_type": self.event_type,
            "is_late": self.is_late,
            "is_missed": self.is_missed,
        }

    def __repr__(self) -> str:
        return f"<InsulinEvent {self.timestamp}: {self.units}U {self.event_type}>"
