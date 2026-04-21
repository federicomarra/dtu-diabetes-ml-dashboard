"""Glucose data business logic."""
from datetime import datetime
from typing import Optional
from app.models.glucose_reading import GlucoseReading


class GlucoseService:
    """Service for glucose data computations."""

    # Clinical glucose target ranges (mmol/L)
    VERY_LOW = 3.0
    LOW = 3.9
    HIGH = 10.0
    VERY_HIGH = 13.9

    @staticmethod
    def calculate_time_in_range(
        patient_id: int,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> dict:
        """Calculate time-in-range (TIR) statistics for a patient.

        Returns percentage of readings in each clinical range:
        - very_low: < 3.0 mmol/L
        - low: 3.0–3.8 mmol/L
        - in_range: 3.9–10.0 mmol/L
        - high: 10.1–13.9 mmol/L
        - very_high: > 13.9 mmol/L
        """
        query = GlucoseReading.query.filter_by(patient_id=patient_id)

        if start:
            query = query.filter(
                GlucoseReading.timestamp >= datetime.fromisoformat(start)
            )
        if end:
            query = query.filter(
                GlucoseReading.timestamp <= datetime.fromisoformat(end)
            )

        readings = query.all()
        total = len(readings)

        if total == 0:
            return {
                "patient_id": patient_id,
                "total_readings": 0,
                "very_low_pct": 0,
                "low_pct": 0,
                "in_range_pct": 0,
                "high_pct": 0,
                "very_high_pct": 0,
            }

        very_low = sum(1 for r in readings if r.glucose_mmoll < GlucoseService.VERY_LOW)
        low = sum(
            1 for r in readings
            if GlucoseService.VERY_LOW <= r.glucose_mmoll < GlucoseService.LOW
        )
        in_range = sum(
            1 for r in readings
            if GlucoseService.LOW <= r.glucose_mmoll <= GlucoseService.HIGH
        )
        high = sum(
            1 for r in readings
            if GlucoseService.HIGH < r.glucose_mmoll <= GlucoseService.VERY_HIGH
        )
        very_high = sum(
            1 for r in readings if r.glucose_mmoll > GlucoseService.VERY_HIGH
        )

        return {
            "patient_id": patient_id,
            "total_readings": total,
            "very_low_pct": round(very_low / total * 100, 1),
            "low_pct": round(low / total * 100, 1),
            "in_range_pct": round(in_range / total * 100, 1),
            "high_pct": round(high / total * 100, 1),
            "very_high_pct": round(very_high / total * 100, 1),
        }
