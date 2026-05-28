-- DTU Diabetes ML Dashboard — Reference Schema
-- PostgreSQL 15+

-- Patients
CREATE TABLE IF NOT EXISTS patients (
    id              SERIAL PRIMARY KEY,
    external_id     VARCHAR(50) UNIQUE NOT NULL,
    name            VARCHAR(120),                   
    date_of_birth   DATE,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_patients_external_id ON patients(external_id);

-- Histories
CREATE TABLE IF NOT EXISTS histories (
    id              SERIAL PRIMARY KEY,
    patient_id      INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    timestamp       TIMESTAMP NOT NULL,
    glucose_mmoll   REAL,
    insulin_U      REAL,
    cho_grams       REAL
    --exercise_ca     REAL,    -- NOT INCLUDED IN SCHEMA FOR NOW
    --created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
);

CREATE INDEX idx_history_patient_time ON histories(patient_id, timestamp);

-- Glucoses
CREATE TABLE IF NOT EXISTS glucoses (
    id              SERIAL PRIMARY KEY,
    patient_id      INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    timestamp       TIMESTAMP NOT NULL,
    glucose_mmoll   REAL NOT NULL,                      -- stored in mmol/L
    source          VARCHAR(20) NOT NULL DEFAULT 'simulated'  -- simulated, dexcom, libre
                        CHECK (source IN ('simulated', 'dexcom', 'libre')),
    status          VARCHAR(20) NOT NULL             -- very_low, low, in_range, high, very_high
                        CHECK (status IN ('very_low', 'low', 'in_range', 'high', 'very_high'))
    --created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_glucose_patient_time ON glucoses(patient_id, timestamp);

-- Insulins
CREATE TABLE IF NOT EXISTS insulins (
    id              SERIAL PRIMARY KEY,
    patient_id      INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    timestamp       TIMESTAMP NOT NULL,
    units           REAL NOT NULL,
    event_type      VARCHAR(10) NOT NULL     -- bolus, basal
                        CHECK (event_type IN ('bolus', 'basal'))
    --created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_insulin_patient_time ON insulins(patient_id, timestamp);

-- Meals
CREATE TABLE IF NOT EXISTS meals (
    id              SERIAL PRIMARY KEY,
    patient_id      INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    timestamp       TIMESTAMP NOT NULL,
    carbs       REAL NOT NULL,
    meal_type       VARCHAR(20)                               -- breakfast, lunch, dinner, snack
                        CHECK (meal_type IN ('breakfast', 'lunch', 'dinner', 'snack'))
    --created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_meal_patient_time ON meals(patient_id, timestamp);

-- Exercises
CREATE TABLE IF NOT EXISTS exercises (
    id                  SERIAL PRIMARY KEY,
    patient_id          INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    timestamp           TIMESTAMP NOT NULL,
    duration_minutes    INTEGER NOT NULL,
    intensity           VARCHAR(10) NOT NULL                  -- low, medium, high
                            CHECK (intensity IN ('low', 'medium', 'high'))
    --created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_exercise_patient_time ON exercises(patient_id, timestamp);

-- Anomalies (ML results)
CREATE TABLE IF NOT EXISTS anomalies (
    id                  SERIAL PRIMARY KEY,
    patient_id          INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    glucose_reading_id  INTEGER REFERENCES glucoses(id),
    anomaly_type        VARCHAR(30) NOT NULL                  
                            CHECK (anomaly_type IN ('missed_bolus', 'late_bolus')),
    confidence          REAL NOT NULL,
    description         TEXT,
    is_acknowledged     BOOLEAN DEFAULT FALSE
    --detected_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_anomaly_patient ON anomalies(patient_id);
