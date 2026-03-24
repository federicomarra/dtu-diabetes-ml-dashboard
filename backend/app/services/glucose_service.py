"""Glucose data business logic."""
from datetime import datetime
from typing import Optional
from app.models.glucose_reading import GlucoseReading


class GlucoseService:
    """Service for glucose data computations."""

    # Clinical glucose target ranges (mg/dL)
    VERY_LOW = 54
    LOW = 70
    HIGH = 180
    VERY_HIGH = 250

    @staticmethod
    def calculate_time_in_range(
        patient_id: int,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> dict:
        """Calculate time-in-range (TIR) statistics for a patient.

        Returns percentage of readings in each clinical range:
        - very_low: < 54 mg/dL
        - low: 54–69 mg/dL
        - in_range: 70–180 mg/dL
        - high: 181–250 mg/dL
        - very_high: > 250 mg/dL
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

        very_low = sum(1 for r in readings if r.glucose_mgdl < GlucoseService.VERY_LOW)
        low = sum(
            1 for r in readings
            if GlucoseService.VERY_LOW <= r.glucose_mgdl < GlucoseService.LOW
        )
        in_range = sum(
            1 for r in readings
            if GlucoseService.LOW <= r.glucose_mgdl <= GlucoseService.HIGH
        )
        high = sum(
            1 for r in readings
            if GlucoseService.HIGH < r.glucose_mgdl <= GlucoseService.VERY_HIGH
        )
        very_high = sum(
            1 for r in readings if r.glucose_mgdl > GlucoseService.VERY_HIGH
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
