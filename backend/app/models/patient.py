"""Patient model."""
from datetime import datetime, date
from app import db


class Patient(db.Model):
    """Represents a patient in the diabetes monitoring system."""
    __tablename__ = "patients"

    id = db.Column(db.Integer, primary_key=True)
    external_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    date_of_birth = db.Column(db.Date, nullable=True)
    diabetes_type = db.Column(
        db.String(10), nullable=False, default="T1D"
    )  # T1D, T2D
    diagnosis_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    glucose_readings = db.relationship(
        "GlucoseReading", backref="patient", lazy="dynamic"
    )
    insulin_events = db.relationship(
        "InsulinEvent", backref="patient", lazy="dynamic"
    )
    meal_events = db.relationship(
        "MealEvent", backref="patient", lazy="dynamic"
    )
    anomaly_detections = db.relationship(
        "AnomalyDetection", backref="patient", lazy="dynamic"
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "external_id": self.external_id,
            "name": self.name,
            "date_of_birth": self.date_of_birth.isoformat() if self.date_of_birth else None,
            "diabetes_type": self.diabetes_type,
            "diagnosis_date": self.diagnosis_date.isoformat() if self.diagnosis_date else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<Patient {self.external_id}: {self.name}>"
