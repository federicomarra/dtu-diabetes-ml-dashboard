"""
inspect_database.py — DTU Diabetes ML Dashboard
================================================
Connects to the local PostgreSQL database and prints a structured report
covering the most interesting aspects of the data.

Usage:
    cd database/
    python inspect_database.py [--url postgresql://user:pass@host:port/db]

Requires: psycopg2-binary  (pip install psycopg2-binary)
"""

import os
import sys
import argparse
import textwrap

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    sys.exit("psycopg2-binary is required.  Run:  pip install psycopg2-binary")

# ── Connection ────────────────────────────────────────────────────────────────

DEFAULT_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/diabetes_db",
)

parser = argparse.ArgumentParser(description="Inspect the diabetes database")
parser.add_argument("--url", default=DEFAULT_URL, help="PostgreSQL connection URL")
args = parser.parse_args()

try:
    conn = psycopg2.connect(args.url)
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SET work_mem = '128MB'")
except Exception as exc:
    sys.exit(f"Could not connect: {exc}")

# ── Helpers ───────────────────────────────────────────────────────────────────

SEP = "─" * 70

def section(title: str) -> None:
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)

def q(sql: str, params=None):
    cur.execute(sql, params)
    return cur.fetchall()

def q1(sql: str, params=None):
    cur.execute(sql, params)
    row = cur.fetchone()
    return row

def table(rows, headers=None) -> None:
    if not rows:
        print("  (no rows)")
        return
    if headers is None:
        headers = list(rows[0].keys())
    col_widths = {h: len(str(h)) for h in headers}
    for row in rows:
        for h in headers:
            col_widths[h] = max(col_widths[h], len(str(row.get(h, ""))))
    fmt = "  " + "  ".join(f"{{:<{col_widths[h]}}}" for h in headers)
    print(fmt.format(*headers))
    print("  " + "  ".join("─" * col_widths[h] for h in headers))
    for row in rows:
        print(fmt.format(*[str(row.get(h, "")) for h in headers]))

# ══════════════════════════════════════════════════════════════════════════════
# 1. Row counts
# ══════════════════════════════════════════════════════════════════════════════

section("1 · ROW COUNTS")
counts = q("""
    SELECT 'patients'  AS tbl, COUNT(*) AS rows FROM patients  UNION ALL
    SELECT 'glucoses',          COUNT(*) FROM glucoses           UNION ALL
    SELECT 'insulins',          COUNT(*) FROM insulins           UNION ALL
    SELECT 'meals',             COUNT(*) FROM meals              UNION ALL
    SELECT 'histories',         COUNT(*) FROM histories          UNION ALL
    SELECT 'exercises',         COUNT(*) FROM exercises          UNION ALL
    SELECT 'anomalies',         COUNT(*) FROM anomalies
    ORDER BY rows DESC
""")
table(counts)

# ══════════════════════════════════════════════════════════════════════════════
# 2. Patient overview
# ══════════════════════════════════════════════════════════════════════════════

section("2 · PATIENT OVERVIEW")
overview = q("""
    SELECT
        p.id,
        p.external_id,
        p.name,
        DATE_PART('year', AGE(p.date_of_birth))::INT                    AS age,
        (SELECT COUNT(*) FROM glucoses WHERE patient_id = p.id)         AS glucose_readings,
        (SELECT COUNT(*) FROM insulins WHERE patient_id = p.id)         AS insulin_events,
        (SELECT COUNT(*) FROM meals    WHERE patient_id = p.id)         AS meal_events,
        (SELECT MIN(timestamp)::DATE FROM glucoses WHERE patient_id = p.id) AS first_reading,
        (SELECT MAX(timestamp)::DATE FROM glucoses WHERE patient_id = p.id) AS last_reading
    FROM patients p
    ORDER BY glucose_readings DESC
    LIMIT 10
""")
table(overview)
total = q1("SELECT COUNT(*) AS n FROM patients")
print(f"\n  (showing top 10 of {total['n']} patients)")

# ══════════════════════════════════════════════════════════════════════════════
# 3. Glucose distribution across all patients
# ══════════════════════════════════════════════════════════════════════════════

section("3 · GLUCOSE DISTRIBUTION  (all patients, mmol/L)")
dist = q("""
    SELECT
        status,
        COUNT(*)                              AS readings,
        ROUND(AVG(glucose_mmoll)::NUMERIC, 2) AS avg_mmoll,
        ROUND(MIN(glucose_mmoll)::NUMERIC, 2) AS min_mmoll,
        ROUND(MAX(glucose_mmoll)::NUMERIC, 2) AS max_mmoll,
        ROUND((COUNT(*) * 100.0 / SUM(COUNT(*)) OVER ())::NUMERIC, 1) AS pct
    FROM glucoses
    GROUP BY status
    ORDER BY
        CASE status
            WHEN 'very_low'  THEN 1
            WHEN 'low'       THEN 2
            WHEN 'in_range'  THEN 3
            WHEN 'high'      THEN 4
            WHEN 'very_high' THEN 5
        END
""")
table(dist)

# ══════════════════════════════════════════════════════════════════════════════
# 4. Per-patient Time-in-Range summary
# ══════════════════════════════════════════════════════════════════════════════

section("4 · TIME-IN-RANGE SUMMARY  (per patient, %)")
tir = q("""
    SELECT
        p.external_id,
        ROUND(100.0 * SUM(CASE WHEN g.status = 'very_low'  THEN 1 ELSE 0 END) / COUNT(*)::NUMERIC, 1) AS very_low,
        ROUND(100.0 * SUM(CASE WHEN g.status = 'low'       THEN 1 ELSE 0 END) / COUNT(*)::NUMERIC, 1) AS low,
        ROUND(100.0 * SUM(CASE WHEN g.status = 'in_range'  THEN 1 ELSE 0 END) / COUNT(*)::NUMERIC, 1) AS in_range,
        ROUND(100.0 * SUM(CASE WHEN g.status = 'high'      THEN 1 ELSE 0 END) / COUNT(*)::NUMERIC, 1) AS high,
        ROUND(100.0 * SUM(CASE WHEN g.status = 'very_high' THEN 1 ELSE 0 END) / COUNT(*)::NUMERIC, 1) AS very_high
    FROM glucoses g
    JOIN patients p ON p.id = g.patient_id
    GROUP BY p.id, p.external_id
    ORDER BY in_range DESC
    LIMIT 10
""")
table(tir)
print("  (top 10 patients by time-in-range, descending)")

# ══════════════════════════════════════════════════════════════════════════════
# 5. Insulin breakdown (bolus vs basal)
# ══════════════════════════════════════════════════════════════════════════════

section("5 · INSULIN EVENTS  (bolus vs basal)")
insulin = q("""
    SELECT
        event_type,
        COUNT(*)                              AS events,
        ROUND(AVG(units)::NUMERIC, 2)         AS avg_units,
        ROUND(MIN(units)::NUMERIC, 2)         AS min_units,
        ROUND(MAX(units)::NUMERIC, 2)         AS max_units,
        ROUND(SUM(units)::NUMERIC, 0)         AS total_units
    FROM insulins
    GROUP BY event_type
""")
table(insulin)

# ══════════════════════════════════════════════════════════════════════════════
# 6. Meal composition
# ══════════════════════════════════════════════════════════════════════════════

section("6 · MEALS  (by type)")
meals = q("""
    SELECT
        COALESCE(meal_type, 'unknown') AS meal_type,
        COUNT(*)                        AS events,
        ROUND(AVG(carbs)::NUMERIC, 1)   AS avg_carbs_g,
        ROUND(MIN(carbs)::NUMERIC, 1)   AS min_carbs_g,
        ROUND(MAX(carbs)::NUMERIC, 1)   AS max_carbs_g
    FROM meals
    GROUP BY meal_type
    ORDER BY events DESC
""")
table(meals)

# ══════════════════════════════════════════════════════════════════════════════
# 7. Glucose temporal coverage
# ══════════════════════════════════════════════════════════════════════════════

section("7 · DATA TEMPORAL COVERAGE")
cov = q1("""
    SELECT
        MIN(timestamp)::DATE  AS earliest,
        MAX(timestamp)::DATE  AS latest,
        (MAX(timestamp)::DATE - MIN(timestamp)::DATE) AS span_days,
        COUNT(DISTINCT patient_id) AS patients_with_data
    FROM glucoses
""")
for k, v in cov.items():
    print(f"  {k:<25} {v}")

# ══════════════════════════════════════════════════════════════════════════════
# 8. Average readings per patient per day
# ══════════════════════════════════════════════════════════════════════════════

section("8 · READINGS PER PATIENT PER DAY")
rpd = q1("""
    SELECT
        ROUND(AVG(daily_count)::NUMERIC, 1) AS avg_readings_per_patient_day,
        MIN(daily_count)                    AS min,
        MAX(daily_count)                    AS max
    FROM (
        SELECT patient_id, DATE(timestamp), COUNT(*) AS daily_count
        FROM glucoses
        GROUP BY patient_id, DATE(timestamp)
    ) sub
""")
for k, v in rpd.items():
    print(f"  {k:<35} {v}")
print("\n  Expected: ~288/day for 5-min CGM, ~1440/day for 1-min CGM")

# ══════════════════════════════════════════════════════════════════════════════
# 9. Anomaly summary
# ══════════════════════════════════════════════════════════════════════════════

section("9 · ANOMALY SUMMARY")
anom = q("""
    SELECT
        anomaly_type,
        COUNT(*)                                                       AS total,
        SUM(CASE WHEN is_acknowledged THEN 1 ELSE 0 END)              AS acknowledged,
        SUM(CASE WHEN NOT is_acknowledged THEN 1 ELSE 0 END)          AS pending,
        ROUND(AVG(confidence)::NUMERIC, 3)                            AS avg_confidence
    FROM anomalies
    GROUP BY anomaly_type
""")
if anom:
    table(anom)
else:
    print("  No anomalies detected yet.")

# ══════════════════════════════════════════════════════════════════════════════
# 10. Patients with extreme glucose profiles
# ══════════════════════════════════════════════════════════════════════════════

section("10 · EXTREME GLUCOSE PROFILES  (worst TIR patients)")
extreme = q("""
    SELECT
        p.external_id,
        ROUND(AVG(g.glucose_mmoll)::NUMERIC, 2)                               AS mean_mmoll,
        ROUND(100.0 * SUM(CASE WHEN g.status IN ('very_low','low') THEN 1 ELSE 0 END) / COUNT(*)::NUMERIC, 1) AS hypo_pct,
        ROUND(100.0 * SUM(CASE WHEN g.status IN ('high','very_high') THEN 1 ELSE 0 END) / COUNT(*)::NUMERIC, 1) AS hyper_pct,
        ROUND(100.0 * SUM(CASE WHEN g.status = 'in_range' THEN 1 ELSE 0 END) / COUNT(*)::NUMERIC, 1)           AS tir_pct
    FROM glucoses g
    JOIN patients p ON p.id = g.patient_id
    GROUP BY p.id, p.external_id
    ORDER BY tir_pct ASC
    LIMIT 10
""")
table(extreme)

# ══════════════════════════════════════════════════════════════════════════════
# Done
# ══════════════════════════════════════════════════════════════════════════════

print(f"\n{SEP}")
print("  Done.")
print(SEP + "\n")

cur.close()
conn.close()
