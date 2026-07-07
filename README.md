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
                         │     (Flask)      │
                         │  localhost:5001  │
                         └──────────────────┘
```

| Component    | Technology                      | Environment    |
|--------------|---------------------------------|----------------|
| Frontend     | Next.js + TypeScript + Recharts | localhost:3000 |
| Backend API  | ASP.NET Core 10 + EF Core       | localhost:8000 |
| Database     | PostgreSQL 16                   | localhost:5432 |
| ML Module    | PyTorch + scikit-learn + Flask  | localhost:5001 |

## Project Structure

```text
├── backend/                        # ASP.NET Core 10 API
│   ├── DiabetesApi/                # Main API project
│   │   ├── Routes/                 # Controller route handlers
│   │   │   ├── Health.cs           # Health check endpoints
│   │   │   ├── Patient.cs          # Patient management
│   │   │   ├── Doctor.cs           # Doctor management
│   │   │   ├── Glucose.cs          # Glucose data
│   │   │   ├── Anomaly.cs          # Anomaly detection
│   │   │   ├── Insulin.cs          # Insulin data
│   │   │   ├── Meal.cs             # Meal data
│   │   │   ├── History.cs          # History data
│   │   │   └── Utils.cs            # Shared time-range parsing utilities
│   │   ├── Models/                 # EF Core entity models
│   │   ├── Data/
│   │   │   ├── AppDbContext.cs     # EF Core DbContext
│   │   │   └── DTOs.cs             # Request/response records
│   │   ├── Services/
│   │   │   ├── GlucoseService.cs   # TIR, average glucose, HbA1c & GMI logic
│   │   │   ├── PatientService.cs   # Age calculation
│   │   │   └── UploadService.cs    # Parquet, CSV, and Glooko ZIP parsing
│   │   ├── Program.cs              # DI, Swagger, CORS, routing
│   │   └── DiabetesApi.csproj
│   ├── DiabetesApi.Tests/          # xUnit integration tests
│   ├── DiabetesApi.slnx            # .NET solution
│   └── Dockerfile                  # Docker container configuration
│
├── frontend/                       # Next.js dashboard
│   └── src/
│       ├── app/                    # Next.js pages (thin shells)
│       │   ├── page.tsx            # Home / landing
│       │   ├── layout.tsx          # Root layout & nav
│       │   ├── patient/
│       │   │   ├── page.tsx        # Patient login & registration portal
│       │   │   └── [ext_id]/       # Patient detail view (shows uploader)
│       │   │       └── page.tsx
│       │   └── doctor/
│       │       ├── page.tsx        # Multi-patient clinician list (paginated, sorted)
│       │       └── [ext_id]/       # Doctor view of patient detail (hides uploader)
│       │           └── page.tsx
│       ├── controllers/           # React hooks & contexts — data & state
│       │   ├── GlucoseUnitContext.tsx
│       │   ├── TimeRangeContext.tsx
│       │   ├── GlucoseRangesContext.tsx
│       │   ├── SeverityInferenceContext.tsx
│       │   ├── usePatientController.ts
│       │   ├── usePatientDetailController.ts
│       │   └── useDoctorController.ts
│       ├── models/                # Types, API client, config
│       │   ├── types.ts           # Shared TypeScript types
│       │   ├── api.ts             # Typed API client with Axios mapping to backend
│       │   ├── glucoseConfig.ts   # Glucose configuration constants
│       │   ├── glucoseUnits.ts    # Glucose unit conversion utilities
│       │   └── demoData.ts          # Demo data for development
│       └── views/                 # Presentational components
│           ├── GlucoseDailyChart/ # Daily CGM line chart with anomaly dots overlay
│           ├── TIRChart/          # Time-in-range chart (stacked/bar) with range editor
│           ├── PatientOverview/   # Summary metrics (average, TIR, alert counts)
│           ├── AnomalyAlert/      # Grid-layout alerts list with severity/date sorting
│           ├── MultiWeeklyChart/  # Overlay comparing multiple weeks of CGM readings
│           ├── GlucoseScatterplot/# Daily averages (mean, min, max) with whiskers
│           ├── CarboDailyChart/   # Daily carbohydrate intake bar chart
│           ├── InsulinDailyChart/ # Daily insulin delivery (basal & bolus) doses chart
│           ├── DataUploader/      # Patient CSV & Glooko ZIP file uploader component
│           ├── PatientDetailView/ # Unified detail view component shared by patient & doctor
│           └── NavBar/            # Navigation bar component
│
├── ml/                            # Machine learning module (Python)
│   ├── dataset.py                 # Data loading, normalisation, sliding-window Dataset
│   ├── data/                      # Parquet cohort, OhioT1DM, checkpoints, scalers
│   │   └── checkpoints/           # Pre-trained model weights
│   │       └── xchannel_nll_pooled_best.pt     # XChannel weights for inference
│   ├── models/                    # One subfolder per model architecture
│   │   ├── patch_tst/             # Arc 1 baseline: PatchTST masked-patch pretraining
│   │   ├── carla/                 # Arc 1 baseline: CARLA contrastive
│   │   └── xchannel/              # Arc 1 primary: iTransformer cross-channel forecaster
│   ├── augment/                   # Data augmentation (sensor artifacts)
│   ├── characterization/          # Classifier head training and evaluation
│   ├── features/                  # Feature engineering utilities (IOB/COB tracking)
│   ├── inference/                 # Stateless microservice (service.py), loaders & detectors
│   ├── ohio_eval/                 # OhioT1DM dataset evaluation adapter
│   ├── hupa_eval/                 # HUPA cohort dataset evaluation adapter
│   ├── realdata/                  # Real patient clinical dataset adapter
│   ├── scripts/                   # One-off analysis and plotting scripts
│   ├── figures/                   # Output figures (thesis-ready, 300 dpi)
│   └── tests/                     # Unit tests (pytest)
│
├── database/                      # Schema & seeding scripts
│   ├── schema.sql                 # Database schema
│   ├── upload_parquet.py          # Upload parquet files to database
│   ├── inspect_parquet.py         # Inspect parquet files
│   ├── inspect_database.py        # Connects to PostgreSQL and prints data report
│   └── docker-compose.db.yml      # DB-only compose specification
│
├── .github/workflows/             # GitHub Actions CI/CD pipelines
│   └── ci.yml                     # Continuous Integration
|
├── .env.example                   # Environment variables configuration
|
└── docker-compose.yml             # Local dev environment
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
# Start all services (database, backend, frontend, ml)
docker compose up --build --detach

# Include pgAdmin for DB inspection
docker compose --profile tools up
```

Services available after startup:

| Service                    | URL                                          |
|----------------------------|----------------------------------------------|
| Frontend                   | http://localhost:3000 (or :3001)             |
| Backend health check       | http://localhost:8000/api/health             |
| Backend Swagger UI         | http://localhost:8000/swagger                |
| ML service health check    | http://localhost:5001/health                 |
| ML service Swagger UI      | http://localhost:5001/swagger                |
| Database pgAdmin           | http://localhost:5050 (admin@dtu.dk / admin) |

### 3. Manual setup (without Docker)

**Database only:**

```bash
docker compose up postgres -d
```

**Backend:**

```bash
cd backend
dotnet restore DiabetesApi.slnx
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

**ML Service:**

```bash
cd ml
pip install -r requirements.txt
python inference/service.py
```

The ml service starts on http://localhost:5001. Its Swagger UI is at http://localhost:5001/swagger.

### 4. Upload your data

You can import and seed telemetry data into the system in three different ways depending on your interface and role:

#### A. Command Line (Developer database seeding)
If you are running the environment locally and want to seed the database directly with simulated dataset files:
```bash
pip install -r database/requirements.txt
python database/upload_parquet.py
```
*This will search the `database/simulated-data/` folder and load the default `.parquet` simulated cohort files.*

#### B. Clinician Dashboard (Cohort Parquet Upload)
If you are logged in as a clinician on the **Doctor Dashboard** (http://localhost:3000/doctor):
1. Locate the **Data Uploader** section.
2. Select and upload a cohort simulation Parquet file (`.parquet`).
3. This registers new patients and loads all their corresponding glucose, insulin, and carb timelines.

#### C. Patient Portal (Individual LibreView CSV or Glooko ZIP Upload)
If you are logged in as an individual patient on the **Patient Portal** (http://localhost:3000/patient/[ext_id]):
1. Use the upload interface inside the dashboard.
2. Choose one of the supported formats:
   - **LibreView CSV**: Abbott Freestyle Libre sensor values, insulin, and carbohydrate logs.
   - **Glooko ZIP**: Zip archive export from Glooko containing raw clinical logs.
3. The backend processes the uploaded archive, parses the data, and updates the patient's records and histories.

### 5. Run tests

**Backend:**
```bash
cd backend
dotnet test
```

**Frontend:**
```bash
cd frontend
npm run lint
```

**ML Module:**
```bash
cd ml
python -m pytest
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
| GET    | `/api/patient/list`          | List all patients (paginated/sorted: `?page=1&perPage=20&sortBy=name|ext_id|age&sortDir=asc|desc`) |
| GET    | `/api/patient?id={id}&ext_id={ext_id}` | Get a single patient by database ID or external ID (requires at least one) |
| POST   | `/api/patient/create`        | Create a new patient (`external_id` + `name` required in body) |
| POST   | `/api/patient/upload-libre-csv?id={id}` | Upload glucose, insulin, and carb data from LibreView CSV |
| POST   | `/api/patient/upload-glooko-zip?id={id}` | Upload glucose, insulin, and carb data from Glooko ZIP export |

### Doctor (`/api/doctor`)

| Method | Endpoint                     | Description                                        |
|--------|------------------------------|----------------------------------------------------|
| POST   | `/api/doctor/upload-parquet` | Upload patient cohort data from a simulation Parquet file |

### Glucose (`/api/glucose`)

| Method | Endpoint                          | Description                                       |
|--------|-----------------------------------|---------------------------------------------------|
| GET    | `/api/glucose?id={id}`            | Get readings (`?start=`, `?end=`, `?last=2w`)     |
| GET    | `/api/glucose/latest?id={id}`     | Most recent glucose reading                       |
| GET    | `/api/glucose/tir?id={id}`        | Time-in-range statistics (`?start=`, `?end=`, `?last=2w` & custom range limits: `?VeryLow=`, `?Low=`, `?High=`, `?VeryHigh=`)|
| GET    | `/api/glucose/average?id={id}`    | Average glucose reading (`?start=`, `?end=`, `?last=2w`)|
| GET    | `/api/glucose/hba1c?id={id}`      | Estimated HbA1c calculation (`?start=`, `?end=`, `?last=2w`)|
| GET    | `/api/glucose/gmi?id={id}`        | Glucose Management Indicator (`?start=`, `?end=`, `?last=2w`)|
| GET    | `/api/glucose/scatterplot?id={id}`| Daily average, min, and max glucose for scatterplot (`?start=`, `?end=`, `?last=2w`)|

### Anomalies (`/api/anomaly`)

| Method | Endpoint                                  | Description                                      |
|--------|-------------------------------------------|--------------------------------------------------|
| GET    | `/api/anomaly?id={id}`                    | List anomalies (`?start=`, `?end=`, `?last=`)    |
| POST   | `/api/anomaly/detect?id={id}`             | Execute ML inference window and save anomalies (`?start=`, `?end=`, `?last=`) |
| POST   | `/api/anomaly/acknowledge?patientId={patientId}&anomalyId={anomalyId}` | Mark anomaly as acknowledged |

### Insulin (`/api/insulin`)

| Method | Endpoint                          | Description                                       |
|--------|-----------------------------------|---------------------------------------------------|
| GET    | `/api/insulin?id={id}`            | Get insulin delivery events (`?start=`, `?end=`, `?last=2w`) |

### Meals (`/api/meal`)

| Method | Endpoint                          | Description                                       |
|--------|-----------------------------------|---------------------------------------------------|
| GET    | `/api/meal?id={id}`               | Get carbohydrate intakes and meals (`?start=`, `?end=`, `?last=2w`) |

### History (`/api/history`)

| Method | Endpoint                          | Description                                       |
|--------|-----------------------------------|---------------------------------------------------|
| GET    | `/api/history?id={id}`            | Get historical telemetry entries (`?start=`, `?end=`, `?last=2w`) |

> 📖 Full interactive API reference via **Swagger UI** at `http://localhost:8000/swagger`

## API Documentation (Swagger)

The backend exposes an auto-generated **OpenAPI 3.0** spec powered by Swashbuckle.

| Resource                    | URL (local Docker)                                                                             |
|-----------------------------|------------------------------------------------------------------------------------------------|
| Swagger UI (interactive)    | [http://localhost:8000/swagger](http://localhost:8000/swagger)                                 |
| Raw OpenAPI 3.0 JSON spec   | [http://localhost:8000/swagger/v1/swagger.json](http://localhost:8000/swagger/v1/swagger.json) |

### How it works

- XML doc comments on routes are automatically parsed to supply endpoint descriptions.
- Request/response payload DTO shapes are documented automatically using EF Core schema/OpenAPI decorators.

## Frontend Pages & Components

### Pages

| Route                    | Component                              | Description                                          |
|--------------------------|----------------------------------------|------------------------------------------------------|
| `/`                      | `app/page.tsx`                         | Home / landing page                                  |
| `/patient`               | `app/patient/page.tsx`                 | Patient Login & Registration portal                 |
| `/patient/[ext_id]`      | `app/patient/[ext_id]/page.tsx`        | Patient dashboard details (renders `PatientDetailView` in patient mode) |
| `/doctor`                | `app/doctor/page.tsx`                  | Multi-patient clinician list with pagination, sorting & search |
| `/doctor/[ext_id]`       | `app/doctor/[ext_id]/page.tsx`         | Doctor view of patient details (renders `PatientDetailView` in doctor mode) |

### Components

| Component | Description |
|-----------|-------------|
| `PatientDetailView` | Unified container component managing view states, rendering layout grids, TIR, daily charts, and anomaly feeds. |
| `GlucoseDailyChart` | 24-hour CGM line chart with custom ranges, glucose ranges limits editing, and integrated anomaly dots. |
| `TIRChart` | Time-in-range stacked/bar visualizations with custom thresholds. |
| `PatientOverview` | Summary metrics card: current glucose, TIR %, and active alarm indicators. |
| `AnomalyAlert` | Multi-card grid listing missed/late bolus detections, supporting sorting by severity/date, and eye-icon acknowledgment with opacity reduction. |
| `MultiWeeklyChart` | Multi-week overlay comparison chart. |
| `GlucoseScatterplot` | Daily glucose averages (mean, min, max) with box-whisker or capsule range overlays. |
| `CarboDailyChart` | Daily carbohydrate intake bar chart (hiding meal tags for "unknown" types). |
| `InsulinDailyChart` | Daily insulin delivery showing basal and bolus doses. |
| `DataUploader` | Patient uploader supporting CSV and ZIP archives with active progress and cancel-prevention during upload. |
| `NavBar` | Global navigation bar. |

## Deployment

> **Note:** For this stage of the project, the application is **not hosted externally**. All services run locally via Docker Compose or manual setup (see [Quick Start](#quick-start) above).
>
> Cloud deployment (e.g. Vercel for the frontend, DTU HPC for the backend & ML training) may be reintroduced in a later phase.

## License

MIT — see [LICENSE](LICENSE)
