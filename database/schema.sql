-- DTU Diabetes ML Dashboard — Reference Schema
-- PostgreSQL 15+

-- Patients
CREATE TABLE IF NOT EXISTS patients (
    id              SERIAL PRIMARY KEY,
    external_id     VARCHAR(50) UNIQUE NOT NULL,
    name            VARCHAR(120),                   -- nullable per Patient interface
    age             INTEGER,                         -- replaces date_of_birth / diagnosis_date
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_patients_external_id ON patients(external_id);

-- Glucose readings (CGM data)
CREATE TABLE IF NOT EXISTS glucose_readings (
    id              SERIAL PRIMARY KEY,
    patient_id      INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    timestamp       TIMESTAMP NOT NULL,
    glucose_mmoll   REAL NOT NULL,                      -- stored in mmol/L
    source          VARCHAR(20) NOT NULL DEFAULT 'simulated'  -- simulated, dexcom, libre
                        CHECK (source IN ('simulated', 'dexcom', 'libre')),
    status          VARCHAR(20) NOT NULL                      -- very_low, low, in_range, high, very_high
                        CHECK (status IN ('very_low', 'low', 'in_range', 'high', 'very_high')),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_glucose_patient_time ON glucose_readings(patient_id, timestamp);

-- Insulin events
CREATE TABLE IF NOT EXISTS insulin_events (
    id              SERIAL PRIMARY KEY,
    patient_id      INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    timestamp       TIMESTAMP NOT NULL,
    units           REAL NOT NULL,
    event_type      VARCHAR(10) NOT NULL                      -- bolus, basal
                        CHECK (event_type IN ('bolus', 'basal')),
    is_late         BOOLEAN DEFAULT FALSE,
    is_missed       BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_insulin_patient_time ON insulin_events(patient_id, timestamp);

-- Meal events
CREATE TABLE IF NOT EXISTS meal_events (
    id              SERIAL PRIMARY KEY,
    patient_id      INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    timestamp       TIMESTAMP NOT NULL,
    carbs_grams     REAL NOT NULL,
    meal_type       VARCHAR(20)                               -- breakfast, lunch, dinner, snack
                        CHECK (meal_type IN ('breakfast', 'lunch', 'dinner', 'snack')),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_meal_patient_time ON meal_events(patient_id, timestamp);

-- Exercise events
CREATE TABLE IF NOT EXISTS exercise_events (
    id                  SERIAL PRIMARY KEY,
    patient_id          INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    timestamp           TIMESTAMP NOT NULL,
    duration_minutes    INTEGER NOT NULL,
    intensity           VARCHAR(10) NOT NULL                  -- low, medium, high
                            CHECK (intensity IN ('low', 'medium', 'high')),
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_exercise_patient_time ON exercise_events(patient_id, timestamp);

-- Anomaly detections (ML results)
CREATE TABLE IF NOT EXISTS anomaly_detections (
    id                  SERIAL PRIMARY KEY,
    patient_id          INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    glucose_reading_id  INTEGER REFERENCES glucose_readings(id),
    anomaly_type        VARCHAR(30) NOT NULL                  -- missed_bolus, late_bolus, unusual_pattern
                            CHECK (anomaly_type IN ('missed_bolus', 'late_bolus', 'unusual_pattern')),
    confidence          REAL NOT NULL,
    description         TEXT,
    is_acknowledged     BOOLEAN DEFAULT FALSE,
    detected_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_anomaly_patient ON anomaly_detections(patient_id);
