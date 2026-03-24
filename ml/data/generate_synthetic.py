"""Synthetic diabetes data generation using simplified models.

This module generates realistic T1D patient data including:
- Continuous glucose monitor (CGM) traces
- Insulin administration events (basal + bolus)
- Meal events with carbohydrate counts
- Simulated missed/late bolus scenarios for anomaly detection

TODO (Phase 3): Replace random-walk model with the Hovorka physiological
model from the existing simulation codebase for higher fidelity data.
"""
import os
import random
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path


def hovorka_glucose_model(
    t_hours: float,
    basal_rate: float = 1.0,
    meals: list[tuple[float, float]] | None = None,
    boluses: list[tuple[float, float]] | None = None,
    dt_minutes: int = 5,
) -> np.ndarray:
    """Simplified glucose dynamics model (placeholder for full Hovorka).

    Args:
        t_hours: Simulation duration in hours.
        basal_rate: Basal insulin rate (U/hr).
        meals: List of (time_hours, carbs_grams) tuples.
        boluses: List of (time_hours, units) tuples.
        dt_minutes: Time step in minutes.

    Returns:
        Array of glucose values in mg/dL at each time step.
    """
    n_steps = int(t_hours * 60 / dt_minutes)
    glucose = np.zeros(n_steps)
    glucose[0] = np.random.uniform(80, 120)

    meals = meals or []
    boluses = boluses or []

    for i in range(1, n_steps):
        t = i * dt_minutes / 60  # Current time in hours

        # Mean-reversion towards fasting glucose (~100 mg/dL)
        drift = (100 - glucose[i - 1]) * 0.015
        noise = np.random.normal(0, 2)

        # Basal insulin effect (continuous glucose lowering)
        basal_effect = -basal_rate * 0.5 * (dt_minutes / 60)

        # Meal absorption (simplified exponential decay)
        meal_effect = 0
        for meal_time, carbs in meals:
            dt_meal = t - meal_time
            if 0 < dt_meal < 4:  # Meal effect lasts ~4 hours
                peak_time = 0.75  # Hours to peak absorption
                meal_effect += (
                    carbs * 0.5 * dt_meal / peak_time
                    * np.exp(1 - dt_meal / peak_time)
                )

        # Bolus insulin effect (faster than basal)
        bolus_effect = 0
        for bolus_time, units in boluses:
            dt_bolus = t - bolus_time
            if 0 < dt_bolus < 5:  # Bolus effect lasts ~5 hours
                peak_time = 1.0  # Hours to peak action
                bolus_effect -= (
                    units * 8 * dt_bolus / peak_time
                    * np.exp(1 - dt_bolus / peak_time)
                )

        glucose[i] = glucose[i - 1] + drift + noise + basal_effect + meal_effect + bolus_effect
        glucose[i] = np.clip(glucose[i], 30, 500)

    return glucose


def generate_patient_data(
    patient_id: str,
    days: int = 7,
    dt_minutes: int = 5,
    missed_bolus_rate: float = 0.10,
    late_bolus_rate: float = 0.15,
) -> dict[str, pd.DataFrame]:
    """Generate a complete synthetic dataset for one patient.

    Args:
        patient_id: Unique patient identifier.
        days: Number of days to simulate.
        dt_minutes: CGM sampling interval in minutes.
        missed_bolus_rate: Probability of missing a meal bolus.
        late_bolus_rate: Probability of a late bolus (if not missed).

    Returns:
        Dictionary with DataFrames: 'glucose', 'insulin', 'meals'.
    """
    all_glucose = []
    all_insulin = []
    all_meals = []

    start_date = datetime.utcnow() - timedelta(days=days)

    for day in range(days):
        day_start = start_date + timedelta(days=day)

        # Define meals for the day
        meal_schedule = [
            (7.5 + random.gauss(0, 0.3), random.uniform(30, 60), "breakfast"),
            (12.5 + random.gauss(0, 0.3), random.uniform(40, 80), "lunch"),
            (18.5 + random.gauss(0, 0.3), random.uniform(50, 90), "dinner"),
        ]

        meals_for_model = [(h, c) for h, c, _ in meal_schedule]
        boluses_for_model = []

        for meal_hour, carbs, meal_type in meal_schedule:
            # Record meal event
            all_meals.append({
                "patient_id": patient_id,
                "timestamp": day_start + timedelta(hours=meal_hour),
                "carbs_grams": round(carbs, 1),
                "meal_type": meal_type,
            })

            # Decide if bolus is given
            if random.random() < missed_bolus_rate:
                all_insulin.append({
                    "patient_id": patient_id,
                    "timestamp": day_start + timedelta(hours=meal_hour),
                    "units": 0,
                    "event_type": "bolus",
                    "is_missed": True,
                    "is_late": False,
                })
            else:
                is_late = random.random() < late_bolus_rate
                delay = random.uniform(0.3, 0.8) if is_late else 0
                bolus_time = meal_hour + delay
                units = carbs / random.uniform(8, 12)  # ICR-based dose

                boluses_for_model.append((bolus_time, units))
                all_insulin.append({
                    "patient_id": patient_id,
                    "timestamp": day_start + timedelta(hours=bolus_time),
                    "units": round(units, 1),
                    "event_type": "bolus",
                    "is_missed": False,
                    "is_late": is_late,
                })

        # Basal insulin (once daily)
        basal_rate = random.uniform(0.8, 1.2)
        all_insulin.append({
            "patient_id": patient_id,
            "timestamp": day_start + timedelta(hours=22),
            "units": round(basal_rate * 24, 1),
            "event_type": "basal",
            "is_missed": False,
            "is_late": False,
        })

        # Generate glucose trace
        glucose_trace = hovorka_glucose_model(
            t_hours=24,
            basal_rate=basal_rate,
            meals=meals_for_model,
            boluses=boluses_for_model,
            dt_minutes=dt_minutes,
        )

        for j, val in enumerate(glucose_trace):
            all_glucose.append({
                "patient_id": patient_id,
                "timestamp": day_start + timedelta(minutes=j * dt_minutes),
                "glucose_mgdl": round(float(val), 1),
                "source": "simulated",
            })

    return {
        "glucose": pd.DataFrame(all_glucose),
        "insulin": pd.DataFrame(all_insulin),
        "meals": pd.DataFrame(all_meals),
    }


def generate_dataset(
    n_patients: int = 10,
    days: int = 14,
    output_dir: str = "data/output",
) -> None:
    """Generate a complete synthetic dataset and save to CSV/Parquet.

    Args:
        n_patients: Number of patients.
        days: Number of days per patient.
        output_dir: Directory for output files.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    all_glucose = []
    all_insulin = []
    all_meals = []

    for i in range(n_patients):
        pid = f"SIM_{i+1:03d}"
        print(f"Generating data for patient {pid}...")
        data = generate_patient_data(pid, days=days)
        all_glucose.append(data["glucose"])
        all_insulin.append(data["insulin"])
        all_meals.append(data["meals"])

    # Concatenate and save
    for name, frames in [
        ("glucose_readings", all_glucose),
        ("insulin_events", all_insulin),
        ("meal_events", all_meals),
    ]:
        df = pd.concat(frames, ignore_index=True)
        df.to_csv(output_path / f"{name}.csv", index=False)
        df.to_parquet(output_path / f"{name}.parquet", index=False)
        print(f"  ✓ {name}: {len(df)} rows")

    print(f"\nDataset saved to {output_path}/")


if __name__ == "__main__":
    generate_dataset()
