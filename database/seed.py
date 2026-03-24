"""Seed the database with synthetic diabetes data.

Usage:
    cd backend && python -m database.seed

Or from project root:
    python database/seed.py
"""
import os
import sys
import random
from datetime import datetime, timedelta

# Add backend to path so we can import the app
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app import create_app, db
from app.models import Patient, GlucoseReading, InsulinEvent, MealEvent


def generate_glucose_trace(
    hours: int = 24, interval_minutes: int = 5
) -> list[float]:
    """Generate a realistic CGM glucose trace using a random walk model.

    Returns glucose values at fixed intervals, oscillating around
    a physiological mean with meal-driven spikes.
    """
    n_points = (hours * 60) // interval_minutes
    glucose = [random.uniform(90, 120)]  # Starting fasting glucose

    for i in range(1, n_points):
        # Random walk with mean-reversion to ~110 mg/dL
        drift = (110 - glucose[-1]) * 0.02
        noise = random.gauss(0, 5)

        # Simulate meal spikes at roughly meal times
        hour_of_day = (i * interval_minutes / 60) % 24
        meal_effect = 0
        if 7 <= hour_of_day <= 8:    # Breakfast
            meal_effect = random.uniform(0, 3)
        elif 12 <= hour_of_day <= 13:  # Lunch
            meal_effect = random.uniform(0, 4)
        elif 18 <= hour_of_day <= 19:  # Dinner
            meal_effect = random.uniform(0, 4)

        new_val = glucose[-1] + drift + noise + meal_effect
        glucose.append(max(40, min(400, new_val)))  # Clamp to safe range

    return glucose


def seed_database(n_patients: int = 5, days: int = 7):
    """Populate the database with synthetic patient data."""
    app = create_app("development")

    with app.app_context():
        print("Creating tables...")
        db.create_all()

        print(f"Seeding {n_patients} patients with {days} days of data each...")

        for i in range(n_patients):
            # Create patient
            patient = Patient(
                external_id=f"SIM_{i+1:03d}",
                name=f"Simulated Patient {i+1}",
                diabetes_type="T1D",
                date_of_birth=datetime(
                    random.randint(1970, 2005),
                    random.randint(1, 12),
                    random.randint(1, 28),
                ).date(),
            )
            db.session.add(patient)
            db.session.flush()  # Get the patient ID

            start_time = datetime.utcnow() - timedelta(days=days)

            for day in range(days):
                day_start = start_time + timedelta(days=day)

                # Generate glucose trace for this day
                glucose_values = generate_glucose_trace(hours=24, interval_minutes=5)
                for j, glucose_val in enumerate(glucose_values):
                    timestamp = day_start + timedelta(minutes=j * 5)
                    reading = GlucoseReading(
                        patient_id=patient.id,
                        timestamp=timestamp,
                        glucose_mgdl=round(glucose_val, 1),
                        source="simulated",
                    )
                    db.session.add(reading)

                # Add meal events (3 meals per day)
                for meal_hour, meal_type, carbs_range in [
                    (7.5, "breakfast", (30, 60)),
                    (12.5, "lunch", (40, 80)),
                    (18.5, "dinner", (50, 90)),
                ]:
                    meal = MealEvent(
                        patient_id=patient.id,
                        timestamp=day_start + timedelta(hours=meal_hour),
                        carbs_grams=random.uniform(*carbs_range),
                        meal_type=meal_type,
                    )
                    db.session.add(meal)

                # Add insulin boluses (sometimes missed for anomaly detection)
                for bolus_hour in [7.5, 12.5, 18.5]:
                    if random.random() > 0.1:  # 10% chance of missed bolus
                        is_late = random.random() < 0.15  # 15% chance of late
                        insulin = InsulinEvent(
                            patient_id=patient.id,
                            timestamp=day_start + timedelta(
                                hours=bolus_hour + (0.5 if is_late else 0)
                            ),
                            units=random.uniform(2, 8),
                            event_type="bolus",
                            is_late=is_late,
                            is_missed=False,
                        )
                        db.session.add(insulin)

                # Add basal insulin
                basal = InsulinEvent(
                    patient_id=patient.id,
                    timestamp=day_start + timedelta(hours=22),
                    units=random.uniform(15, 25),
                    event_type="basal",
                )
                db.session.add(basal)

            print(f"  ✓ Patient {patient.external_id} seeded")

        db.session.commit()
        print(f"\nDone! Seeded {n_patients} patients with {days} days of data.")


if __name__ == "__main__":
    seed_database()
