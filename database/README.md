# Database

PostgreSQL database for the DTU Diabetes ML Dashboard.

## Prerequisites

The `diabetes-db` Docker container must be running. Start it from the project root:

```bash
docker compose up -d postgres
```

---

## Schema

### Rebuild from scratch (drop all tables and recreate)

```bash
docker exec -i diabetes-db psql -U postgres -d diabetes_db \
    -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;" \
  && docker exec -i diabetes-db psql -U postgres -d diabetes_db < schema.sql
```

### Apply schema without dropping (create tables if not exist)

```bash
docker exec -i diabetes-db psql -U postgres -d diabetes_db < schema.sql
```

---

## Load Parquet Data

Run from the `database/` directory.

### First install the Python dependencies for the upload script:

```bash
pip install -r requirements.txt
```

### Load the default simulated dataset (auto-discovers `simulated-data/*.parquet`)

```bash
python upload_parquet.py
```

### Load a specific parquet file

```bash
python upload_parquet.py simulated-data/results_20000p_14d.parquet
```

### Load and clear all existing data first (`--clear`)

```bash
python upload_parquet.py simulated-data/results_20000p_14d.parquet --clear
```

### Full options

```bash
python upload_parquet.py <path/to/file.parquet> \
    --db-url postgresql://postgres:postgres@localhost:5432/diabetes_db \
    --batch-size 10080 \   # rows per INSERT batch (default: 7 days in minutes)
    --clear                # truncate all tables before loading
```

---

## Query the Database

Open an interactive psql session inside the container:

```bash
docker exec -it diabetes-db psql -U postgres -d diabetes_db
```

Run a one-shot query without entering the shell:

```bash
docker exec diabetes-db psql -U postgres -d diabetes_db -c "<SQL QUERY HERE>"
```

### Useful example queries

```bash
# List all tables
docker exec diabetes-db psql -U postgres -d diabetes_db -c "\dt"

# Count rows per table
docker exec diabetes-db psql -U postgres -d diabetes_db -c "
  SELECT 'patients'  AS tbl, COUNT(*) FROM patients  UNION ALL
  SELECT 'histories',         COUNT(*) FROM histories UNION ALL
  SELECT 'glucoses',          COUNT(*) FROM glucoses  UNION ALL
  SELECT 'insulins',          COUNT(*) FROM insulins  UNION ALL
  SELECT 'meals',             COUNT(*) FROM meals     UNION ALL
  SELECT 'exercises',         COUNT(*) FROM exercises UNION ALL
  SELECT 'anomalies',         COUNT(*) FROM anomalies;
"

# Preview patients
docker exec diabetes-db psql -U postgres -d diabetes_db -c "SELECT * FROM patients LIMIT 10;"

# Preview glucose readings for patient 1
docker exec diabetes-db psql -U postgres -d diabetes_db -c "SELECT * FROM glucoses WHERE patient_id = 1 LIMIT 20;"

# Preview histories for patient 1
docker exec diabetes-db psql -U postgres -d diabetes_db -c "SELECT * FROM histories WHERE patient_id = 1 LIMIT 20;"

# Preview insulin events for patient 1
docker exec diabetes-db psql -U postgres -d diabetes_db -c "SELECT * FROM insulins WHERE patient_id = 1 LIMIT 20;"

# Preview meals for patient 1
docker exec diabetes-db psql -U postgres -d diabetes_db -c "SELECT * FROM meals WHERE patient_id = 1 LIMIT 20;"
```

---

## Inspect the Database  (`inspect_database.py`)

A Python script that connects directly to PostgreSQL and prints a structured
report covering the most interesting aspects of the data.

**Requires:** `psycopg2-binary`

```bash
pip install psycopg2-binary
```

**Run from the `database/` directory:**

```bash
# Uses DATABASE_URL from .env (default: postgresql://postgres:postgres@localhost:5432/diabetes_db)
python inspect_database.py

# Or pass a custom connection URL
python inspect_database.py --url postgresql://user:pass@host:port/db
```

**Sections reported:**

| # | Section | What it shows |
|---|---|---|
| 1 | Row counts | Total rows in every table |
| 2 | Patient overview | Top 10 patients — age, reading counts, date range |
| 3 | Glucose distribution | Status breakdown (very low → very high): count, avg/min/max mmol/L, % |
| 4 | Time-in-Range per patient | Top 10 patients by TIR%, all 5 zone percentages |
| 5 | Insulin events | Bolus vs basal: count, avg/min/max/total units |
| 6 | Meals by type | Breakfast/lunch/dinner/snack: count, avg/min/max carbs |
| 7 | Temporal coverage | Earliest/latest date, total span, patients with data |
| 8 | Readings per patient/day | Avg/min/max daily reading rate |
| 9 | Anomaly summary | By type: total, acknowledged, pending, avg confidence |
| 10 | Worst TIR patients | Bottom 10 by TIR%: mean glucose, hypo%, hyper%, TIR% |

---

## Files

| File | Description |
|---|---|
| `schema.sql` | PostgreSQL DDL — all table and index definitions |
| `upload_parquet.py` | Loads a `.parquet` simulation file into the database |
| `inspect_parquet.py` | Prints column names and sample rows from a parquet file |
| `inspect_database.py` | Connects to PostgreSQL and prints a 10-section data report |
| `simulated-data/` | Directory containing `.parquet` simulation output files |
