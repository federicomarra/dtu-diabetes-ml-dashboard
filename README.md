# DTU Diabetes ML Dashboard

**Type 1 Diabetes monitoring system** with continuous glucose monitoring, insulin tracking, and ML-powered anomaly detection for missed and late boluses.

> DTU Research Project — Currently run locally (Docker or manual setup)

## Architecture

```text
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│     Frontend     │     │     Backend      │     │     Database     │
│    TypeScript    │     │        C#        │     │       SQL        │
│    (Next.js)     │────▶│    (.NET 10)     │────▶│   (PostgreSQL)   │
│  localhost:3000  │     │  localhost:8000  │     │  localhost:5432  │
└──────────────────┘     └──────────────────┘     └──────────────────┘
                                  │
                                  │
                                  ▼
                         ┌──────────────────┐
                         │        ML        │
                         │      Python      │
                         │    (PyTorch)     │
                         │  local / DTU HPC │
                         └──────────────────┘
```

| Component    | Technology                               | Environment             |
|--------------|------------------------------------------|-------------------------|
| Frontend     | Next.js + TypeScript + Recharts          | localhost:3000 or :3001 |
| Backend API  | ASP.NET Core 10 + EF Core + Swashbuckle  | localhost:8000          |
| Database     | PostgreSQL 16                            | localhost:5432    |
| ML Module    | PyTorch + scikit-learn                   | Local / DTU HPC   |

## Project Structure

```text
├── backend/                       # ASP.NET Core 10 API
│   ├── DiabetesApi/               # Main API project
│   │   ├── Routes/                # Minimal-API route handlers
│   │   │   ├── Health.cs
│   │   │   ├── Patient.cs
│   │   │   ├── Glucose.cs
│   │   │   ├── Anomaly.cs
│   │   │   ├── Insulin.cs
│   │   │   ├── Meal.cs
│   │   │   └── History.cs
│   │   ├── Models/                # EF Core entity models
│   │   │   ├── Patient.cs
│   │   │   ├── Glucose.cs
│   │   │   ├── Anomaly.cs
│   │   │   ├── Insulin.cs
│   │   │   ├── Meal.cs
│   │   │   ├── Exercise.cs
│   │   │   └── History.cs
│   │   ├── Data/
│   │   │   ├── AppDbContext.cs    # EF Core DbContext
│   │   │   └── DTOs.cs            # Request/response records
│   │   ├── Services/
│   │   │   ├── GlucoseService.cs  # TIR & reading business logic
│   │   │   └── PatientService.cs  # Age calculation
│   │   ├── Program.cs             # DI, Swagger, CORS, routing
│   │   └── DiabetesApi.csproj
│   ├── DiabetesApi.Tests/         # xUnit integration tests
│   │   ├── ApiTests.cs
│   │   └── CustomWebApplicationFactory.cs
│   ├── DiabetesApi.slnx
│   └── Dockerfile
│
├── frontend/                      # Next.js dashboard
│   └── src/
│       ├── app/                   # Next.js pages (thin shells)
│       │   ├── page.tsx           # Home / landing
│       │   ├── layout.tsx         # Root layout & nav
│       │   ├── patient/page.tsx   # Single-patient dashboard
│       │   └── doctor/
│       │       ├── page.tsx       # Multi-patient clinician view (paginated)
│       │       └── [patient_id]/page.tsx  # Patient detail
│       ├── controllers/           # React hooks & contexts — data & state
│       │   ├── GlucoseUnitContext.tsx
│       │   ├── TimeRangeContext.tsx
│       │   ├── GlucoseRangesContext.tsx
│       │   ├── usePatientController.ts
│       │   ├── usePatientDetailController.ts
│       │   └── useDoctorController.ts
│       ├── models/                # Types, API client, config
│       │   ├── types.ts
│       │   ├── api.ts
│       │   ├── glucoseConfig.ts
│       │   ├── glucoseUnits.ts
│       │   └── demoData.ts
│       └── views/                 # Presentational components
│           ├── GlucoseChart/      # 24-hour CGM line chart (Recharts)
│           ├── TIRChart/          # Time-in-range chart with custom ranges
│           ├── PatientOverview/   # Summary card with key metrics
│           ├── AnomalyAlert/      # Alert list with acknowledge action
│           ├── MultiWeeklyChart/  # Multi-week comparison glucose chart (Recharts)
│           └── NavBar/            # Navigation bar component
│
├── ml/                            # Machine learning module (Python)
│   ├── dataset.py                 # Data loading, normalisation, sliding-window Dataset
│   ├── data/                      # Parquet cohort, OhioT1DM, checkpoints, scalers
│   ├── models/                    # One subfolder per model architecture
│   │   ├── patch_tst/             # Arc 1 baseline: PatchTST masked-patch pretraining
│   │   ├── carla/                 # Arc 1 baseline: CARLA contrastive
│   │   └── xchannel/              # Arc 1 primary: iTransformer cross-channel forecaster
│   ├── inference/                 # DB→model adapter (diary.py; loader.py = histories→array)
│   ├── ohio_eval/ hupa_eval/ realdata/  # Real-dataset adapters + proxy-label eval
│   ├── scripts/                   # One-off analysis and plotting scripts
│   ├── figures/                   # Output figures (thesis-ready, 300 dpi)
│   ├── tests/                     # Unit tests (pytest)
│   └── docs/                      # Design specs (gitignored)
├── database/                      # Schema & seeding scripts
|   ├── schema.sql                 # Database schema
|   ├── upload_parquet.py          # Upload parquet files to database
|   ├── inspect_parquet.py         # Inspect parquet files
|   ├── inspect_database.py        # Inspect database
|
├── docker-compose.yml             # Local dev environment
|
├── Jenkinsfile                    # CI/CD pipeline (DTU HPC)
|
└── hpc_job.sh                     # DTU HPC LSF job script (DTU HPC)
```

## Quick Start

### Prerequisites

- [.NET 10 SDK](https://dotnet.microsoft.com/download)
- [Node.js 18+](https://nodejs.org/)
- [Docker](https://docker.com/)

### 1. Clone & configure

```bash
git clone https://github.com/federicomarra/dtu-diabetes-ml-dashboard.git
cd dtu-diabetes-ml-dashboard
cp .env.example .env
```

### 2. Start with Docker (recommended)

```bash
# Start all services (database, backend, frontend)
docker compose up

# Include pgAdmin for DB inspection
docker compose --profile tools up
```

Services available after startup:

| Service     | URL                                      |
|-------------|------------------------------------------|
| Frontend    | http://localhost:3000 (or :3001 if 3000 is occupied) |
| Backend API | http://localhost:8000/api/health         |
| Swagger UI  | http://localhost:8000/swagger            |
| OpenAPI JSON| http://localhost:8000/swagger/v1/swagger.json |
| pgAdmin     | http://localhost:5050 (admin@dtu.dk / admin) |

### 3. Manual setup (without Docker)

**Database only:**

```bash
docker compose up postgres -d
```

**Backend:**

```bash
cd backend
dotnet restore DiabetesApi.sln
dotnet run --project DiabetesApi/DiabetesApi.csproj
```

The API starts on `http://localhost:8000`. Swagger UI is at `http://localhost:8000/swagger`.

**Frontend:**

```bash
cd frontend
npm install
npm run dev
```

The frontend starts on `http://localhost:3000` (or `http://localhost:3001` if `3000` is occupied).

### 4. Seed synthetic data

```bash
python database/seed.py
```

### 5. Run backend tests

```bash
cd backend
dotnet test DiabetesApi.Tests/ -v
```

## API Endpoints

All routes are prefixed with `/api` and served by ASP.NET Core.

### Health

| Method | Endpoint      | Description                                   |
|--------|-------------- |-----------------------------------------------|
| GET    | `/api/health` | Health check — returns `{"status":"healthy"}` |

### Patients (`/api/patient`)

| Method | Endpoint                     | Description                                        |
|--------|------------------------------|----------------------------------------------------|
| GET    | `/api/patient/list`          | List all patients (paginated: `?page=1&per_page=20`) |
| GET    | `/api/patient/{id}`          | Get a single patient by database ID                |
| GET    | `/api/patient/by-external/{externalId}` | Get a single patient by external ID string |
| POST   | `/api/patient/create`        | Create a new patient (`external_id` + `name` required) |

### Glucose (`/api/glucose`)

| Method | Endpoint                          | Description                                       |
|--------|-----------------------------------|---------------------------------------------------|
| GET    | `/api/glucose?id={patient_id}`       | Get readings (`?start=`, `?end=`, `?last=2w`)    |
| GET    | `/api/glucose/latest?id={patient_id}`| Most recent glucose reading                      |
| GET    | `/api/glucose/tir?id={patient_id}`   | Time-in-range statistics (`?start=`, `?end=`, `?last=2w`)|
| GET    | `/api/glucose/average?id={patient_id}`| Average glucose reading (`?start=`, `?end=`, `?last=2w`)|
| GET    | `/api/glucose/hba1c?id={patient_id}`  | Estimated HbA1c calculation (`?start=`, `?end=`, `?last=2w`)|
| GET    | `/api/glucose/gmi?id={patient_id}`    | Glucose Management Indicator (`?start=`, `?end=`, `?last=2w`)|
| GET    | `/api/glucose/scatterplot?id={patient_id}` | Daily average, min, and max glucose for scatterplot (`?start=`, `?end=`, `?last=2w`)|

### Anomalies (`/api/anomaly`)

| Method | Endpoint                                  | Description                                      |
|--------|-------------------------------------------|--------------------------------------------------|
| GET    | `/api/anomaly/{patient_id}`               | List anomalies (`?acknowledged=true/false`, `?limit=50`) |
| POST   | `/api/anomaly/{anomaly_id}/acknowledge`   | Mark anomaly as acknowledged                    |

### Insulin (`/api/insulin`)

| Method | Endpoint                          | Description                                       |
|--------|-----------------------------------|---------------------------------------------------|
| GET    | `/api/insulin/{patient_id}`       | Get insulin delivery events (`?start=`, `?end=`, `?last=2w`) |

### Meals (`/api/meal`)

| Method | Endpoint                          | Description                                       |
|--------|-----------------------------------|---------------------------------------------------|
| GET    | `/api/meal/{patient_id}`          | Get carbohydrate intakes and meals (`?start=`, `?end=`, `?last=2w`) |

### History (`/api/history`)

| Method | Endpoint                          | Description                                       |
|--------|-----------------------------------|---------------------------------------------------|
| GET    | `/api/history/{patient_id}`       | Get historical telemetry entries (`?start=`, `?end=`, `?last=2w`) |

> 📖 Full interactive API reference via **Swagger UI** at `http://localhost:8000/swagger`

## API Documentation (Swagger)

The backend exposes an auto-generated **OpenAPI 3.0** spec powered by [Swashbuckle](https://github.com/domaindrivendev/Swashbuckle.AspNetCore).

| Resource                    | URL (local Docker)                                                                             |
|-----------------------------|------------------------------------------------------------------------------------------------|
| Swagger UI (interactive)    | [http://localhost:8000/swagger](http://localhost:8000/swagger)                                 |
| Raw OpenAPI 3.0 JSON spec   | [http://localhost:8000/swagger/v1/swagger.json](http://localhost:8000/swagger/v1/swagger.json) |

### How it works

- Controller XML doc comments are automatically included as endpoint descriptions.
- Each controller maps to a **tag** group in the Swagger UI (Patients, Glucose, Anomalies, Health).
- `ProducesResponseType` attributes document response schemas.

## Frontend Pages & Components

### Pages

| Route                    | Component                              | Description                                          |
|--------------------------|----------------------------------------|------------------------------------------------------|
| `/`                      | `app/page.tsx`                         | Home / landing page                                  |
| `/patient`               | `app/patient/page.tsx`                 | Single-patient CGM dashboard                         |
| `/doctor`                | `app/doctor/page.tsx`                  | Multi-patient clinician overview with pagination     |
| `/doctor/[patient_id]`   | `app/doctor/[patient_id]/page.tsx`     | Individual patient detail (glucose chart, TIR, anomalies) |

### Components

| Component | Description |
|-----------|-------------|
| `GlucoseChart` | 24-hour CGM line chart with colour-coded threshold lines and shaded target zone; respects custom ranges |
| `TIRChart` | Time-in-range chart (stacked or bar view) with customisable glucose thresholds and unit-aware range editor |
| `PatientOverview` | Summary card — latest glucose reading, TIR %, and unacknowledged anomaly count |
| `AnomalyAlert` | Alert list displaying missed/late bolus detections with inline acknowledge button |
| `MultiWeeklyChart` | Overlay comparison chart comparing multiple weeks of CGM readings to observe patterns |
| `GlucoseScatterplot` | Daily glucose averages (average, min, max) with error bar/whisker or capsule range overlays |
| `CarboDailyChart` | Daily carbohydrate intake bar chart representing patient meal/carb data over time |
| `InsulinDailyChart` | Daily insulin delivery chart showing basal and bolus doses delivered to the patient |
| `NavBar` | Top navigation bar providing navigation between Patient and Doctor dashboards |

## Deployment

> **Note:** For this stage of the project, the application is **not hosted externally**. All services run locally via Docker Compose or manual setup (see [Quick Start](#quick-start) above).
>
> Cloud deployment (e.g. Vercel for the frontend, DTU HPC for the backend & ML training) may be reintroduced in a later phase.

## License

MIT — see [LICENSE](LICENSE)
