"""Meal event model."""
from datetime import datetime
from app import db


class MealEvent(db.Model):
    """Represents a meal intake event with carbohydrate information."""
    __tablename__ = "meal_events"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(
        db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True
    )
    timestamp = db.Column(db.DateTime, nullable=False, index=True)
    carbs_grams = db.Column(db.Float, nullable=False)
    meal_type = db.Column(
        db.String(20), nullable=True
    )  # breakfast, lunch, dinner, snack
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.Index("ix_meal_patient_time", "patient_id", "timestamp"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "timestamp": self.timestamp.isoformat(),
            "carbs_grams": self.carbs_grams,
            "meal_type": self.meal_type,
        }

    def __repr__(self) -> str:
        return f"<MealEvent {self.timestamp}: {self.carbs_grams}g carbs>"
