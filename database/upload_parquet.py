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
import calendar
import json
import os
import random
import sys
import glob
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv


DEFAULT_BATCH_SIZE = 7*24*60 # seven days in minutes
DEFAULT_CLEAR = False        # do not clear tables by default

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_DB_URL = "postgresql://postgres:postgres@localhost:5432/diabetes_db"
def load_glucose_thresholds() -> list[tuple[float, str]]:
    config_path = Path(__file__).parent.parent / "frontend" / "glucose-config.json"
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


def collapse_runs(series: pd.Series, flag_value: float = 0.0) -> pd.Series:
    """Collapse contiguous non-zero runs into their sum at the run's first index.

    Example: [0, 0, 3, 3, 3, 0] → [0, 0, 9, 0, 0, 0]
    """
    result = series.copy()
    in_run = False
    run_start = None
    run_sum = 0.0
    for idx in series.index:
        val = series[idx]
        if val > flag_value:
            if not in_run:
                in_run = True
                run_start = idx
                run_sum = float(val)
            else:
                run_sum += float(val)
                result[idx] = flag_value
        else:
            if in_run:
                result[run_start] = run_sum
                in_run = False
                run_start = None
                run_sum = 0.0
    if in_run:  # series ended mid-run
        result[run_start] = run_sum
    return result
    

def meal_type(minute_of_day: int) -> str | None:
    if 300 <= minute_of_day < 540:   # 05:00–09:00 → breakfast
        return "breakfast"
    if 660 <= minute_of_day < 840:   # 11:00–14:00 → lunch
        return "lunch"
    if 1020 <= minute_of_day < 1320: # 17:00–22:00 → dinner
        return "dinner"
    return "snack"

# ---------------------------------------------------------------------------
# Table loaders
# ---------------------------------------------------------------------------

def upload_patients(cur, df: pd.DataFrame, base_dt: datetime, simulation_days: int) -> dict[int, int]:
    """Insert patients; return {sim_patient_id: db_patient_id}."""
    patients_df = (
        df[["patient_id", "patient_age_years"]]
        .drop_duplicates("patient_id")
        .sort_values("patient_id")
    )

    sql = """
        INSERT INTO patients (external_id, name, date_of_birth)
        VALUES (%s, %s, %s)
        ON CONFLICT (external_id) DO UPDATE
            SET date_of_birth = EXCLUDED.date_of_birth,
                updated_at = CURRENT_TIMESTAMP
        RETURNING external_id, id
    """
    id_map: dict[int, int] = {}
    for _, row in patients_df.iterrows():
        id = f"{int(row['patient_id']):06d}"
        ext_id = f"SIM_{id}"
        name   = f"Simulated patient {id}"
        rng        = random.Random(int(row["patient_id"]))  # deterministic per patient
        birth_year = base_dt.year - int(row["patient_age_years"])
        birth_month = rng.randint(1, 12)
        birth_day   = rng.randint(1, calendar.monthrange(birth_year, birth_month)[1])
        dob = base_dt.replace(year=birth_year, month=birth_month, day=birth_day).date()
        cur.execute(sql, (ext_id, name, dob))
        result = cur.fetchone()
        # result may be None if ON CONFLICT UPDATE doesn't RETURN for existing rows
        if result is None:
            cur.execute("SELECT id FROM patients WHERE external_id = %s", (ext_id))
            result = cur.fetchone()
        id_map[int(row["patient_id"])] = result[1] if result else None

    print(f"  ✓ patients: {len(id_map)} upserted")
    return id_map


def upload_histories(
    cur, df: pd.DataFrame, id_map: dict[int, int], batch_size: int, base_dt: datetime
) -> None:
    """Insert history rows."""
    sql = """
        INSERT INTO histories (patient_id, timestamp, glucose_mmoll, insulin_u, cho_grams)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
    """
    # Collapse cho_mg_min per patient: each non-zero run becomes sum at its first minute.
    df = df.copy()
    for pid, grp in df.groupby("patient_id"):
        df.loc[grp.index, "cho_mg_min"] = collapse_runs(grp["cho_mg_min"])

    rows = []
    for _, row in df.iterrows():
        db_pid = id_map.get(int(row["patient_id"]))
        if db_pid is None:
            continue
        ts     = minute_to_timestamp(base_dt, row["absolute_minute"])
        glucose_mmol = round(float(row["blood_glucose"]), 1)
        insulin_u = round(float(row["insulin_mU_min"]) / 1000, 3)
        cho_grams = round(float(row["cho_mg_min"]) / 1000, 0)
        #exercise_ca = float(row["exercise_overlay"])
        rows.append((db_pid, ts, glucose_mmol, insulin_u, cho_grams))
    n = execute_batch(cur, sql, rows, batch_size)
    print(f"  ✓ histories: {n} inserted")


def upload_glucoses(
    cur, df: pd.DataFrame, id_map: dict[int, int], batch_size: int, base_dt: datetime
) -> dict[tuple[int, int], int]:
    """Insert one glucose reading per minute row; return {(patient_id, abs_min): db_id}."""
    sql = """
        INSERT INTO glucoses (patient_id, timestamp, glucose_mmoll, source, status)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
    """
    rows = []
    for _, row in df.iterrows():
        db_pid = id_map.get(int(row["patient_id"]))
        if db_pid is None:
            continue
        ts     = minute_to_timestamp(base_dt, row["absolute_minute"])
        mmol   = round(float(row["blood_glucose"]), 1)
        source = "simulated"
        status = glucose_status(mmol)
        rows.append((db_pid, ts, mmol, source, status))

    n = execute_batch(cur, sql, rows, batch_size)
    print(f"  ✓ glucose_readings: {n} inserted")


def upload_insulins(
    cur, df: pd.DataFrame, id_map: dict[int, int], batch_size: int, base_dt: datetime, basal_mU_flag_value: float = 0.1 * 1000
) -> None:
    """Insert bolus events (collapsed per bout) and basal events (hourly sums)."""
    df = df.copy()

    sql = """
        INSERT INTO insulins (patient_id, timestamp, units, event_type)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT DO NOTHING
    """
    rows = []

    for pid, grp in df.groupby("patient_id"):
        db_pid = id_map.get(int(pid))
        if db_pid is None:
            continue
        grp = grp.sort_values("absolute_minute")

        # --- Boluses: collapse runs above basal threshold ---
        collapsed = collapse_runs(grp["insulin_mU_min"], flag_value=basal_mU_flag_value)
        for idx in collapsed[collapsed > basal_mU_flag_value].index:
            ts = minute_to_timestamp(base_dt, grp.loc[idx, "absolute_minute"])
            units = round(float(collapsed[idx]) / 1000, 2)
            rows.append((db_pid, ts, units, "bolus"))

        # --- Basals: hourly sums + zero when stopped ---
        is_basal = (grp["insulin_mU_min"] > 0) & (grp["insulin_mU_min"] <= basal_mU_flag_value)
        basal_grp = grp[is_basal]
        if not basal_grp.empty:
            hours = (basal_grp["absolute_minute"] // 60).astype(int)
            for hour, hour_idx in hours.groupby(hours):
                ts = minute_to_timestamp(base_dt, int(hour * 60))
                units = round(float(basal_grp.loc[hour_idx.index, "insulin_mU_min"].sum()) / 1000, 2)
                rows.append((db_pid, ts, units, "basal"))

        # Zero marker when basal stops (first minute after a basal run)
        was_basal = is_basal.shift(1, fill_value=False)
        stops = grp[was_basal & ~is_basal & (grp["insulin_mU_min"] <= basal_mU_flag_value)]
        for idx in stops.index:
            ts = minute_to_timestamp(base_dt, grp.loc[idx, "absolute_minute"])
            rows.append((db_pid, ts, 0.0, "basal"))

        # Zero marker when basal resumes after a stop (end of zero period)
        prev_was_zero = (grp["insulin_mU_min"].shift(1, fill_value=1) == 0)
        resumes = grp[is_basal & ~was_basal & prev_was_zero]
        for idx in resumes.index:
            ts = minute_to_timestamp(base_dt, grp.loc[idx, "absolute_minute"] - 1)
            rows.append((db_pid, ts, 0.0, "basal"))

    # Sort again the insulins by patient_id and timestamp to ensure insertion order integrity
    rows.sort(key=lambda r: (r[0], r[1]))
    n = execute_batch(cur, sql, rows, batch_size)
    print(f"  ✓ insulin_events: {n} inserted")


def upload_meals(
    cur, df: pd.DataFrame, id_map: dict[int, int], batch_size: int, base_dt: datetime
) -> None:
    """Insert a meal event at the first minute of each meal bout."""
    # Collapse cho_mg_min per patient: each non-zero run becomes sum at its first minute.
    df = df.copy()
    for pid, grp in df.groupby("patient_id"):
        df.loc[grp.index, "cho_mg_min"] = collapse_runs(grp["cho_mg_min"])

    df_meal = df[df["cho_mg_min"] > 0].copy()
    if df_meal.empty:
        print("  ✓ meals: 0 inserted (no CHO rows)")
        return

    # Mark bout starts — after collapse_runs, only the first minute of each run is > 0.
    df_sorted = df.sort_values(["patient_id", "absolute_minute"])
    starts = df_sorted[df_sorted["cho_mg_min"] > 0].copy()

    sql = """
        INSERT INTO meals (patient_id, timestamp, carbs, meal_type)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT DO NOTHING
    """
    rows = []
    for _, row in starts.iterrows():
        db_pid = id_map.get(int(row["patient_id"]))
        if db_pid is None:
            continue
        ts = minute_to_timestamp(base_dt, row["absolute_minute"])
        carbs = round(float(row["cho_mg_min"]) / 1000, 0)
        mtype  = meal_type(int(row["minute"]))
        rows.append((db_pid, ts, carbs, mtype))

    n = execute_batch(cur, sql, rows, batch_size)
    print(f"  ✓ meal_events: {n} inserted")



def upload_exercise_events(
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
        INSERT INTO exercises (patient_id, timestamp, duration_minutes, intensity)
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


def upload_anomalies(
    cur, df: pd.DataFrame, id_map: dict[int, int], batch_size: int, base_dt: datetime
) -> None:
    """Insert anomaly detections from missed/late bolus flags."""
    sql = """
        INSERT INTO anomalies
            (patient_id, anomaly_type, confidence, description, is_acknowledged)
        VALUES (%s, %s, %s, %s, FALSE)
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
            #ts,
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
            #ts,
        ))

    n = execute_batch(cur, sql, rows, batch_size)
    print(f"  ✓ anomaly_detections: {n} inserted")


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def upload(parquet_path: str, db_url: str, batch_size: int = DEFAULT_BATCH_SIZE, clear: bool = DEFAULT_CLEAR) -> None:
    print(f"\n📂  Loading: {parquet_path}")
    df = pd.read_parquet(parquet_path)
    print(f"    Rows: {len(df):,}  |  Columns: {list(df.columns)}")

    # Simulation epoch: use today minus 14 days to make the simulated data
    # appear as if it was recorded two weeks ago, so the plots show up 
    # in the "History" tab as "Past 14 days"
    simulation_days = int(df['day'].max()) if pd.notna(df['day'].max()) else 14
    base_dt = datetime.now(timezone.utc) - timedelta(days=simulation_days)

    print(f"\n🔌  Connecting to database …")
    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    cur = conn.cursor()

    try:
        if clear:
            print("🗑️   Clearing existing data …")
            # Order matters due to FK constraints
            # TODO: remove old table names
            for table in [
                "patients",
                "histories",
                "glucoses", 
                "insulins", 
                "meals", 
                # "exercises",
                # "anomalies"
            ]:
                try:
                    cur.execute("SAVEPOINT truncate_sp")
                    cur.execute(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE")
                    cur.execute("RELEASE SAVEPOINT truncate_sp")
                except psycopg2.errors.UndefinedTable:
                    cur.execute("ROLLBACK TO SAVEPOINT truncate_sp")
                    print(f"    ⚠️  Table '{table}' not found, skipping.")
            print("    Tables truncated.")

        print("\n⏳  Inserting data …")
        id_map = upload_patients(cur, df, base_dt, simulation_days)
        upload_histories(cur, df, id_map, batch_size, base_dt)
        upload_glucoses(cur, df, id_map, batch_size, base_dt)
        upload_meals(cur, df, id_map, batch_size, base_dt)
        upload_insulins(cur, df, id_map, batch_size, base_dt)
        # upload_exercises(cur, df, id_map, batch_size, base_dt)
        # upload_anomalies(cur, df, id_map, batch_size, base_dt)

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
        default=DEFAULT_BATCH_SIZE,
        help="Number of rows per INSERT batch (default: 10080, 7 days in minutes).",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Truncate all tables before loading (DELETES ALL EXISTING DATA).",
    )

    args = parser.parse_args()

    db_url = resolve_db_url(args.db_url)
    if args.parquet:
        path = args.parquet
    else:
        files = glob.glob('simulated-data/*.parquet')
        if not files:
            print("Error: No parquet files found in database/simulated-data")
            sys.exit(1)
        else:
            path = files[0]

    upload(path, db_url, args.batch_size, args.clear)


if __name__ == "__main__":
    main()