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
├── backend/              # Flask API server
│   ├── app/              # Application package
│   │   ├── models/       # SQLAlchemy ORM models
│   │   ├── routes/       # API blueprints
│   │   ├── services/     # Business logic
│   │   └── config.py     # Environment config
│   ├── tests/            # Backend tests
│   └── wsgi.py           # Gunicorn entrypoint
├── frontend/             # Next.js dashboard
│   └── src/
│       ├── app/          # Pages (patient, doctor)
│       ├── components/   # Chart & UI components
│       ├── lib/          # API client
│       └── types/        # TypeScript interfaces
├── ml/                   # Machine learning module
│   ├── data/             # Synthetic data generation
│   ├── training/         # Model training
│   └── inference/        # Prediction service
├── database/             # Schema & seeding
├── docker-compose.yml    # Local dev environment
├── vercel.json           # Vercel deployment config
└── hpc_job.sh            # DTU HPC job script
```

## Quick Start

### Prerequisites
- [Node.js 18+](https://nodejs.org/)
- [Python 3.10+](https://python.org/)
- [Docker & Docker Compose](https://docker.com/)

### 1. Clone & configure
```bash
git clone https://github.com/YOUR_USERNAME/dtu-diabetes-ml-dashboard.git
cd dtu-diabetes-ml-dashboard
cp .env.example .env
```

### 2. Start with Docker (recommended)
```bash
# Start all services (backend, frontend, database)
docker compose up

# Include pgAdmin for DB inspection
docker compose --profile tools up
```

Services:
- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:5000/api/health
- **pgAdmin**: http://localhost:5050 (admin@dtu.dk / admin)

### 3. Manual setup (without Docker)

**Database:**
```bash
docker compose -f database/docker-compose.db.yml up -d
```

**Backend:**
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
flask db upgrade  # Run migrations
python ../database/seed.py  # Seed with synthetic data
gunicorn --bind 0.0.0.0:5000 --reload wsgi:app
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

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/patients/` | List patients (paginated) |
| POST | `/api/patients/` | Create patient |
| GET | `/api/patients/:id` | Get patient details |
| GET | `/api/glucose/:patient_id` | Get glucose readings |
| GET | `/api/glucose/:patient_id/latest` | Latest glucose reading |
| GET | `/api/glucose/:patient_id/tir` | Time-in-range stats |
| GET | `/api/anomalies/:patient_id` | Get detected anomalies |
| POST | `/api/anomalies/:id/acknowledge` | Acknowledge anomaly |

## DTU HPC Deployment

```bash
# Run API server
bsub < hpc_job.sh api

# Run ML training (GPU)
bsub < hpc_job.sh train

# Generate synthetic data
bsub < hpc_job.sh generate

# Seed database
bsub < hpc_job.sh seed
```

## Vercel Deployment

1. Connect the GitHub repo to Vercel
2. Set framework to **Next.js**
3. Set root directory to `frontend`
4. Add environment variable: `HPC_BACKEND_URL=http://your-hpc-ip:5000`
5. Deploy

## License

MIT — see [LICENSE](LICENSE)
