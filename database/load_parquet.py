"""Load simulated patient data from a Parquet file into the database.

Parquet columns expected
------------------------
patient_id, patient_age_years, day, minute, absolute_minute, time,
blood_glucose (mmol/L), cho_mg_min, insulin_mU_min, base_scenario,
had_large_meal, had_missed_bolus, n_late_boluses, exercise_overlay,
bolus_status, meal_size, exercise_type, scenario_id, missed_meal_id,
late_bolus_id, late_bolus_ids

Note: blood_glucose values are stored as mmol/L in the database.

Tables populated
----------------
patients            – one row per unique patient_id
glucose_readings    – one row per minute (blood_glucose)
meal_events         – rows where cho_mg_min > 0 (meal start minutes)
insulin_events      – bolus rows (bolus_status != 'none') + basal proxy
exercise_events     – rows where exercise_overlay != 'none' (event starts)
anomaly_detections  – missed boluses and late boluses inferred from flags

Usage
-----
    python database/load_parquet.py path/to/simulation.parquet

    # Additional options:
    python database/load_parquet.py data.parquet \\
        --db-url postgresql://postgres:postgres@localhost:5432/diabetes_db \\
        --batch-size 5000 \\
        --clear          # truncate tables first (keeps schema intact)

Environment
-----------
If --db-url is not passed the script reads DATABASE_URL from .env or the
environment, falling back to the default local URL.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_DB_URL = "postgresql://postgres:postgres@localhost:5432/diabetes_db"
def load_glucose_thresholds() -> list[tuple[float, str]]:
    config_path = Path(__file__).parent.parent / "glucose-config.json"
    try:
        with open(config_path, "r") as f:
            config = json.load(f)
        return [
            (float(config["VERY_LOW_THRESHOLD"]), "very_low"),
            (float(config["LOW_THRESHOLD"]), "low"),
            (float(config["HIGH_THRESHOLD"]), "in_range"),
            (float(config["VERY_HIGH_THRESHOLD"]), "high"),
        ]
    except Exception as e:
        print(f"Warning: Could not load {config_path}, using defaults. Error: {e}")
        return [
            (3.0,  "very_low"),
            (3.9,  "low"),
            (10.0, "in_range"),
            (13.9, "high"),
        ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def resolve_db_url(cli_url: str | None) -> str:
    if cli_url:
        return cli_url
    load_dotenv(Path(__file__).parent.parent / ".env")
    return os.environ.get("DATABASE_URL", _DEFAULT_DB_URL)


def glucose_status(mgdl: float) -> str:
    glucose_status_THRESHOLDS = load_glucose_thresholds()

    for threshold, label in glucose_status_THRESHOLDS:
        if mgdl < threshold:
            return label
    return "very_high"


def minute_to_timestamp(base: datetime, absolute_minute: int) -> datetime:
    """Convert an absolute simulation minute to a UTC datetime."""
    return base.replace(tzinfo=timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) + pd.Timedelta(minutes=int(absolute_minute))


def execute_batch(cur, sql: str, rows: list[tuple], batch_size: int) -> int:
    total = 0
    for start in range(0, len(rows), batch_size):
        chunk = rows[start : start + batch_size]
        psycopg2.extras.execute_batch(cur, sql, chunk, page_size=batch_size)
        total += len(chunk)
    return total


# ---------------------------------------------------------------------------
# Table loaders
# ---------------------------------------------------------------------------

def load_patients(cur, df: pd.DataFrame) -> dict[int, int]:
    """Insert patients; return {sim_patient_id: db_patient_id}."""
    patients_df = (
        df[["patient_id", "patient_age_years"]]
        .drop_duplicates("patient_id")
        .sort_values("patient_id")
    )

    sql = """
        INSERT INTO patients (external_id, name, age)
        VALUES (%s, %s, %s)
        ON CONFLICT (external_id) DO UPDATE
            SET age = EXCLUDED.age,
                updated_at = CURRENT_TIMESTAMP
        RETURNING external_id, id
    """
    id_map: dict[int, int] = {}
    for _, row in patients_df.iterrows():
        id = f"{int(row['patient_id']):06d}"
        ext_id = f"SIM_{id}"
        name   = f"Simulated patient {id}"
        age    = int(row["patient_age_years"]) if pd.notna(row["patient_age_years"]) else None
        cur.execute(sql, (ext_id, name, age))
        result = cur.fetchone()
        # result may be None if ON CONFLICT UPDATE doesn't RETURN for existing rows
        if result is None:
            cur.execute("SELECT id FROM patients WHERE external_id = %s", (ext_id,))
            result = cur.fetchone()
        id_map[int(row["patient_id"])] = result[1] if result else None

    print(f"  ✓ patients: {len(id_map)} upserted")
    return id_map


def load_glucose_readings(
    cur, df: pd.DataFrame, id_map: dict[int, int], batch_size: int, base_dt: datetime
) -> dict[tuple[int, int], int]:
    """Insert one glucose reading per minute row; return {(patient_id, abs_min): db_id}."""
    sql = """
        INSERT INTO glucose_readings (patient_id, timestamp, glucose_mmoll, source, status)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
    """
    rows = []
    for _, row in df.iterrows():
        db_pid = id_map.get(int(row["patient_id"]))
        if db_pid is None:
            continue
        ts     = minute_to_timestamp(base_dt, row["absolute_minute"])
        mmoll  = float(row["blood_glucose"])  # parquet already in mmol/L
        status = glucose_status(mmoll)
        rows.append((db_pid, ts, mmoll, "simulated", status))

    n = execute_batch(cur, sql, rows, batch_size)
    print(f"  ✓ glucose_readings: {n} inserted")


def load_meal_events(
    cur, df: pd.DataFrame, id_map: dict[int, int], batch_size: int, base_dt: datetime
) -> None:
    """Insert a meal event at the first minute of each meal bout."""
    # A meal bout starts when cho_mg_min transitions from 0 → >0.
    # We identify the first minute of each continuous run of cho_mg_min > 0
    # per patient, and use meal_size + had_large_meal to pick the meal type.
    df_meal = df[df["cho_mg_min"] > 0].copy()
    if df_meal.empty:
        print("  ✓ meal_events: 0 inserted (no CHO rows)")
        return

    # Mark bout starts (first minute after a gap or start of data)
    df_sorted = df.sort_values(["patient_id", "absolute_minute"])
    mask_cho   = df_sorted["cho_mg_min"] > 0
    prev_cho   = mask_cho.shift(1, fill_value=False)
    same_pat   = df_sorted["patient_id"] == df_sorted["patient_id"].shift(1)
    bout_start = mask_cho & ~(prev_cho & same_pat)

    starts = df_sorted[bout_start].copy()

    def _meal_type(row) -> str | None:
        minute_of_day = int(row["absolute_minute"]) % 1440
        if 300 <= minute_of_day < 540:   # 05:00–09:00 → breakfast
            return "breakfast"
        if 660 <= minute_of_day < 840:   # 11:00–14:00 → lunch
            return "lunch"
        if 1020 <= minute_of_day < 1200: # 17:00–20:00 → dinner
            return "dinner"
        return "snack"

    sql = """
        INSERT INTO meal_events (patient_id, timestamp, carbs_grams, meal_type)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT DO NOTHING
    """
    rows = []
    for _, row in starts.iterrows():
        db_pid = id_map.get(int(row["patient_id"]))
        if db_pid is None:
            continue
        ts = minute_to_timestamp(base_dt, row["absolute_minute"])
        # cho_mg_min is mg/min; convert a typical 5-min window to approximate grams
        # (rough: grams ≈ cho_mg_min * 5 / 1000 * some_factor – keep as-is scaled)
        carbs  = float(row["meal_size"]) if pd.notna(row.get("meal_size")) else float(row["cho_mg_min"]) * 5.0
        mtype  = _meal_type(row)
        rows.append((db_pid, ts, carbs, mtype))

    n = execute_batch(cur, sql, rows, batch_size)
    print(f"  ✓ meal_events: {n} inserted")


def load_insulin_events(
    cur, df: pd.DataFrame, id_map: dict[int, int], batch_size: int, base_dt: datetime
) -> None:
    """Insert bolus events from bolus_status column and a daily basal proxy."""
    # Bolus events: rows where bolus_status is not 'none' / NaN / empty
    bolus_mask = df["bolus_status"].notna() & (df["bolus_status"].astype(str).str.lower() != "none")
    df_bolus   = df[bolus_mask].copy()

    sql = """
        INSERT INTO insulin_events (patient_id, timestamp, units, event_type, is_late, is_missed)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
    """
    rows = []

    # Bolus events
    for _, row in df_bolus.iterrows():
        db_pid = id_map.get(int(row["patient_id"]))
        if db_pid is None:
            continue
        ts       = minute_to_timestamp(base_dt, row["absolute_minute"])
        units    = float(row["insulin_mU_min"]) if float(row["insulin_mU_min"]) > 0 else 1.0
        status   = str(row["bolus_status"]).lower()
        is_late  = "late" in status
        is_missed = bool(row.get("had_missed_bolus", False))
        rows.append((db_pid, ts, units, "bolus", is_late, is_missed))

    # Basal proxy: one row per patient per day using the mean insulin_mU_min
    # where bolus_status == 'none' (background infusion)
    basal_df = df[~bolus_mask].copy()
    if not basal_df.empty:
        basal_df["day_abs"] = (basal_df["absolute_minute"] // 1440).astype(int)
        daily_basal = (
            basal_df.groupby(["patient_id", "day_abs"])["insulin_mU_min"]
            .mean()
            .reset_index()
        )
        for _, row in daily_basal.iterrows():
            db_pid = id_map.get(int(row["patient_id"]))
            if db_pid is None:
                continue
            abs_min = int(row["day_abs"]) * 1440 + 22 * 60  # 22:00 each day
            ts      = minute_to_timestamp(base_dt, abs_min)
            units   = float(row["insulin_mU_min"]) * 1440  # daily total
            rows.append((db_pid, ts, units, "basal", False, False))

    n = execute_batch(cur, sql, rows, batch_size)
    print(f"  ✓ insulin_events: {n} inserted")


def load_exercise_events(
    cur, df: pd.DataFrame, id_map: dict[int, int], batch_size: int, base_dt: datetime
) -> None:
    """Insert exercise events at the start of each exercise bout."""
    # exercise_overlay contains the type string (or 'none'/NaN when inactive)
    ex_mask = df["exercise_overlay"].notna() & (
        df["exercise_overlay"].astype(str).str.lower() != "none"
    )
    if not ex_mask.any():
        print("  ✓ exercise_events: 0 inserted (no exercise rows)")
        return

    df_sorted = df.sort_values(["patient_id", "absolute_minute"])
    ex_mask_s  = df_sorted["exercise_overlay"].notna() & (
        df_sorted["exercise_overlay"].astype(str).str.lower() != "none"
    )
    prev_ex    = ex_mask_s.shift(1, fill_value=False)
    same_pat   = df_sorted["patient_id"] == df_sorted["patient_id"].shift(1)
    bout_start = ex_mask_s & ~(prev_ex & same_pat)

    starts = df_sorted[bout_start].copy()

    # Compute bout duration (minutes in each contiguous block)
    df_sorted["_ex_active"] = ex_mask_s.astype(int)
    df_sorted["_bout_id"]   = (bout_start).cumsum()
    bout_lengths = (
        df_sorted[ex_mask_s]
        .groupby("_bout_id")
        .size()
        .rename("duration_minutes")
        .reset_index()
    )
    starts["_bout_id"] = bout_start[bout_start].cumsum().values
    starts = starts.merge(bout_lengths, on="_bout_id", how="left")

    def _intensity(ex_type: str) -> str:
        t = str(ex_type).lower()
        if "high" in t or "intense" in t or "vigorous" in t:
            return "high"
        if "medium" in t or "moderate" in t:
            return "medium"
        return "low"

    sql = """
        INSERT INTO exercise_events (patient_id, timestamp, duration_minutes, intensity)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT DO NOTHING
    """
    rows = []
    for _, row in starts.iterrows():
        db_pid = id_map.get(int(row["patient_id"]))
        if db_pid is None:
            continue
        ts        = minute_to_timestamp(base_dt, row["absolute_minute"])
        duration  = int(row["duration_minutes"]) if pd.notna(row.get("duration_minutes")) else 30
        intensity = _intensity(row.get("exercise_type") or row.get("exercise_overlay") or "low")
        rows.append((db_pid, ts, duration, intensity))

    n = execute_batch(cur, sql, rows, batch_size)
    print(f"  ✓ exercise_events: {n} inserted")


def load_anomaly_detections(
    cur, df: pd.DataFrame, id_map: dict[int, int], batch_size: int, base_dt: datetime
) -> None:
    """Insert anomaly detections from missed/late bolus flags."""
    sql = """
        INSERT INTO anomaly_detections
            (patient_id, anomaly_type, confidence, description, is_acknowledged, detected_at)
        VALUES (%s, %s, %s, %s, FALSE, %s)
        ON CONFLICT DO NOTHING
    """
    rows = []

    # Missed boluses: had_missed_bolus flag transitions 0→1
    missed_mask = df["had_missed_bolus"].astype(bool)
    df_sorted   = df.sort_values(["patient_id", "absolute_minute"])
    prev_missed = missed_mask.shift(1, fill_value=False)
    same_pat    = df_sorted["patient_id"] == df_sorted["patient_id"].shift(1)

    # Re-align after sort
    missed_mask  = df_sorted["had_missed_bolus"].astype(bool)
    prev_missed  = missed_mask.shift(1, fill_value=False)
    onset_missed = missed_mask & ~(prev_missed & same_pat)

    for _, row in df_sorted[onset_missed].iterrows():
        db_pid = id_map.get(int(row["patient_id"]))
        if db_pid is None:
            continue
        ts = minute_to_timestamp(base_dt, row["absolute_minute"])
        rows.append((
            db_pid, "missed_bolus", 0.95,
            f"Missed bolus detected (scenario {row.get('scenario_id', '?')})",
            ts,
        ))

    # Late boluses: n_late_boluses > 0 transitions
    late_mask   = df_sorted["n_late_boluses"].fillna(0).astype(int) > 0
    prev_late   = late_mask.shift(1, fill_value=False)
    onset_late  = late_mask & ~(prev_late & same_pat)

    for _, row in df_sorted[onset_late].iterrows():
        db_pid = id_map.get(int(row["patient_id"]))
        if db_pid is None:
            continue
        ts = minute_to_timestamp(base_dt, row["absolute_minute"])
        rows.append((
            db_pid, "late_bolus", 0.90,
            f"{int(row['n_late_boluses'])} late bolus(es) detected (scenario {row.get('scenario_id', '?')})",
            ts,
        ))

    n = execute_batch(cur, sql, rows, batch_size)
    print(f"  ✓ anomaly_detections: {n} inserted")


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def load(parquet_path: str, db_url: str, batch_size: int, clear: bool) -> None:
    print(f"\n📂  Loading: {parquet_path}")
    df = pd.read_parquet(parquet_path)
    print(f"    Rows: {len(df):,}  |  Columns: {list(df.columns)}")

    # Simulation epoch: use 2024-01-01 as day-0 anchor
    base_dt = datetime(2024, 1, 1, tzinfo=timezone.utc)

    print(f"\n🔌  Connecting to database …")
    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    cur = conn.cursor()

    try:
        if clear:
            print("🗑️   Clearing existing data …")
            # Order matters due to FK constraints
            for table in [
                "anomaly_detections", "exercise_events",
                "insulin_events", "meal_events",
                "glucose_readings", "patients",
            ]:
                cur.execute(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE")
            print("    Tables truncated.")

        print("\n⏳  Inserting data …")
        id_map = load_patients(cur, df)
        load_glucose_readings(cur, df, id_map, batch_size, base_dt)
        load_meal_events(cur, df, id_map, batch_size, base_dt)
        load_insulin_events(cur, df, id_map, batch_size, base_dt)
        load_exercise_events(cur, df, id_map, batch_size, base_dt)
        load_anomaly_detections(cur, df, id_map, batch_size, base_dt)

        conn.commit()
        print("\n✅  Done! All data committed successfully.")

    except Exception as exc:
        conn.rollback()
        print(f"\n❌  Error: {exc}", file=sys.stderr)
        raise
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load simulated patient data from a Parquet file into the diabetes DB."
    )
    parser.add_argument(
        "parquet",
        metavar="FILE.parquet",
        help="Path to the simulation Parquet file.",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="PostgreSQL connection URL (default: DATABASE_URL env var or local dev URL).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5000,
        help="Number of rows per INSERT batch (default: 5000).",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Truncate all tables before loading (DELETES ALL EXISTING DATA).",
    )
    args = parser.parse_args()

    db_url = resolve_db_url(args.db_url)
    load(args.parquet, db_url, args.batch_size, args.clear)


if __name__ == "__main__":
    main()
