# DTU Diabetes ML Dashboard

**Type 1 Diabetes monitoring system** with continuous glucose monitoring, insulin tracking, and ML-powered anomaly detection for missed and late boluses.

> DTU Research Project — Deployed on Vercel (frontend) + DTU HPC (backend & ML)

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Frontend   │────▶│   Backend    │────▶│  PostgreSQL  │
│  (Next.js)   │     │   (Flask)    │     │   Database   │
│   Vercel     │     │   DTU HPC    │     │   DTU HPC    │
└──────────────┘     └──────────────┘     └──────────────┘
                            │
                     ┌──────┴──────┐
                     │  ML Module  │
                     │  (PyTorch)  │
                     │  DTU HPC    │
                     └─────────────┘
```

| Component | Technology | Deployment |
|-----------|-----------|------------|
| Frontend | Next.js + TypeScript + Recharts | Vercel |
| Backend API | Flask + SQLAlchemy + Gunicorn | DTU HPC |
| Database | PostgreSQL 16 | DTU HPC / Docker |
| ML Module | PyTorch + scikit-learn | DTU HPC (GPU) |

## Project Structure

```
├── backend/                  # Flask API server
│   ├── app/
│   │   ├── models/           # SQLAlchemy ORM models
│   │   │   ├── patient.py
│   │   │   ├── glucose_reading.py
│   │   │   ├── insulin_event.py
│   │   │   ├── meal_event.py
│   │   │   └── anomaly_detection.py
│   │   ├── routes/           # API blueprints (flask-smorest)
│   │   │   ├── patients.py
│   │   │   ├── glucose.py
│   │   │   └── anomalies.py
│   │   ├── services/         # Business logic
│   │   │   ├── glucose_service.py
│   │   │   └── anomaly_service.py
│   │   ├── utils/            # Shared helpers
│   │   └── config.py         # Environment config
│   ├── tests/                # Backend tests
│   ├── requirements.txt
│   └── wsgi.py               # Gunicorn entrypoint
├── frontend/                 # Next.js dashboard
│   └── src/
│       ├── app/
│       │   ├── page.tsx          # Home / landing
│       │   ├── patient/page.tsx  # Single-patient dashboard
│       │   └── doctor/page.tsx   # Multi-patient clinician view
│       ├── components/
│       │   ├── GlucoseChart.tsx  # 24-hour CGM line chart (Recharts)
│       │   ├── TIRBarChart.tsx   # Time-in-range stacked bar
│       │   ├── PatientOverview.tsx # Summary card with key metrics
│       │   └── AnomalyAlert.tsx  # Alert list with acknowledge action
│       ├── lib/              # API client
│       └── types/            # TypeScript interfaces
├── ml/                       # Machine learning module
│   ├── data/                 # Synthetic data generation
│   ├── training/             # Model training (train_anomaly.py)
│   └── inference/            # Prediction service
├── database/                 # Schema & seeding scripts
├── docker-compose.yml        # Local dev environment
├── vercel.json               # Vercel deployment config
├── Jenkinsfile               # CI/CD pipeline
└── hpc_job.sh                # DTU HPC LSF job script
```

## Quick Start

### Prerequisites
- [Node.js 18+](https://nodejs.org/)
- [Python 3.10+](https://python.org/)
- [Docker & Docker Compose](https://docker.com/)

### 1. Clone & configure
```bash
git clone https://github.com/federicomarra/dtu-diabetes-ml-dashboard.git
cd dtu-diabetes-ml-dashboard
cp .env.example .env
```

### 2. Start with Docker (recommended)
```bash
# Start all services (postgres, backend, frontend)
docker compose up

# Include pgAdmin for DB inspection
docker compose --profile tools up
```

Services available after startup:
| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:5001/api/health |
| Swagger UI | http://localhost:5001/api/swagger |
| OpenAPI JSON | http://localhost:5001/api/openapi.json |
| pgAdmin | http://localhost:5050 (admin@dtu.dk / admin) |

### 3. Manual setup (without Docker)

**Database only:**
```bash
docker compose up postgres -d
```

**Backend:**
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
flask db upgrade          # Apply migrations
python ../database/seed.py  # Seed with synthetic data
gunicorn --bind 0.0.0.0:5000 --workers 2 --reload wsgi:app
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

### 4. Seed synthetic data
```bash
python database/seed.py
```

## API Endpoints

All routes are prefixed with `/api` and served by Flask via `flask-smorest`.

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Health check — returns `{"status": "healthy"}` |

### Patients (`/api/patients`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/patients/list` | List all patients (paginated: `?page=1&per_page=20`) |
| POST | `/api/patients/create` | Create a new patient (`external_id` + `name` required) |
| GET | `/api/patients/<id>` | Get a single patient by ID |

### Glucose (`/api/glucose`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/glucose/<patient_id>` | Get readings (`?start=`, `?end=`, `?limit=500`) |
| GET | `/api/glucose/<patient_id>/latest` | Most recent glucose reading |
| GET | `/api/glucose/<patient_id>/tir` | Time-in-range statistics (`?start=`, `?end=`) |

### Anomalies (`/api/anomalies`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/anomalies/<patient_id>` | List anomalies (`?acknowledged=true/false`, `?limit=50`) |
| POST | `/api/anomalies/<anomaly_id>/acknowledge` | Mark anomaly as acknowledged |

> 📖 Full interactive API reference available via **Swagger UI** — see the section below.

## API Documentation (Swagger)

The backend exposes an auto-generated **OpenAPI 3.0** spec powered by [`flask-smorest`](https://flask-smorest.readthedocs.io/).

| Resource | URL (local Docker) |
|----------|-------------------|
| Swagger UI (interactive) | http://localhost:5001/api/swagger |
| Raw OpenAPI 3.0 JSON spec | http://localhost:5001/api/openapi.json |

### How it works

- Route docstrings are automatically picked up as endpoint descriptions.
- Each Blueprint maps to a **tag** group in the Swagger UI (Patients, Glucose, Anomalies).
- Request/response bodies can be documented by adding `@blp.arguments(Schema)` and `@blp.response(200, Schema)` decorators.

### Example — adding response schema to a route

```python
from marshmallow import Schema, fields
from app.routes.patients import patients_bp

class PatientSchema(Schema):
    id            = fields.Int(dump_only=True)
    name          = fields.Str()
    external_id   = fields.Str()
    diabetes_type = fields.Str()

@patients_bp.route("/<int:patient_id>", methods=["GET"])
@patients_bp.response(200, PatientSchema)   # ← shows response body in Swagger
def get_patient(patient_id: int):
    """Get a single patient by ID."""
    ...
```

## Frontend Pages & Components

### Pages

| Route | Component | Description |
|-------|-----------|-------------|
| `/` | `app/page.tsx` | Home / landing page |
| `/patient` | `app/patient/page.tsx` | Single-patient CGM dashboard |
| `/doctor` | `app/doctor/page.tsx` | Multi-patient clinician overview |

### Components

| Component | Description |
|-----------|-------------|
| `GlucoseChart` | 24-hour CGM line chart with colour-coded glucose zones (Recharts) |
| `TIRBarChart` | Stacked time-in-range bar chart (very low / low / in-range / high / very high) |
| `PatientOverview` | Summary card — current glucose, TIR%, and anomaly alert count |
| `AnomalyAlert` | Alert list displaying missed/late bolus detections with acknowledge button |

> The frontend currently ships with realistic **demo data** for layout/testing. Replace the `DEMO_*` constants with live API calls from `@/lib/api` when the backend is running.

## DTU HPC Deployment

The `hpc_job.sh` script supports four modes submitted via LSF `bsub`:

```bash
# Run Flask API server (4 CPU cores, 8 GB RAM, 24 h wall-time)
bsub < hpc_job.sh api

# Run ML training (enable GPU lines in hpc_job.sh first)
bsub < hpc_job.sh train

# Generate synthetic CGM data
bsub < hpc_job.sh generate

# Seed database with generated data
bsub < hpc_job.sh seed
```

Default LSF resources: `-q hpc -n 4 -W 24:00 -R "rusage[mem=8GB]"`.  
For GPU training, uncomment the `gpuv100` queue and CUDA module lines in `hpc_job.sh`.

## Vercel Deployment

1. Connect the GitHub repo to Vercel
2. Set framework to **Next.js** and root directory to `frontend`
3. Add environment variable: `NEXT_PUBLIC_API_URL=http://your-hpc-ip:5000/api`
4. Deploy

## License

MIT — see [LICENSE](LICENSE)
