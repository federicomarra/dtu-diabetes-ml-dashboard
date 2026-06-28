# DTU Diabetes ML Dashboard — Frontend

A Next.js dashboard built with **TypeScript**, **React 19**, **Recharts** for visualizations, and **React Query** for caching and state synchronisation. It serves as both a clinician portal and a patient monitoring interface.

## Getting Started

### 1. Installation

Ensure you have [Node.js 18+](https://nodejs.org/) installed, navigate to the `frontend` directory, and run:

```bash
npm install
```

### 2. Environment Configuration

The frontend connects to the ASP.NET Core backend. Create a `.env.local` file in the `frontend` folder (or configure it in your environment) to customize the API URL:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000/api
```

- If `NEXT_PUBLIC_API_URL` is omitted, it defaults to `http://localhost:8000/api`.

### 3. Running Locally

Start the local development server:

```bash
npm run dev
```

The application will start on [http://localhost:3000](http://localhost:3000) (or automatically fallback to `http://localhost:3001` if port 3000 is occupied).

### 4. Build for Production

To build and run the production server:

```bash
npm run build
npm run start
```

---

## Project Structure & Routing

The frontend utilizes Next.js **App Router** for layout and page navigation:

```
frontend/src/
├── app/                        # Next.js App Router folders & page entries
│   ├── page.tsx                # Landing Page
│   ├── layout.tsx              # Navigation bar wrapper and global contexts
│   ├── patient/                # Patient-facing portal
│   │   └── page.tsx            # Single-patient view
│   └── doctor/                 # Clinician portal
│       ├── page.tsx            # Multi-patient dashboard (paginated lists)
│       └── [patient_id]/       # Patient detail path
│           └── page.tsx        # Individual clinical dashboard
│
├── controllers/                # Business logic, state hooks, and Context Providers
│   ├── GlucoseUnitContext.tsx  # Handles mmol/L vs mg/dL selection & conversion
│   ├── TimeRangeContext.tsx    # Manages active time range filters (24h, 7d, 2w, 1m)
│   ├── GlucoseRangesContext.tsx# Manages custom low/high target thresholds
│   ├── usePatientController.ts # Logic for patient listing and creating patients
│   └── usePatientDetailController.ts # Aggregates glucose, insulin, carb, anomaly data
│
├── models/                     # Data models, type definitions, and API client
│   ├── types.ts                # TypeScript interfaces
│   ├── api.ts                  # Axios-based API client for backend communication
│   └── glucoseConfig.ts        # Default thresholds and unit conversion formulas
│
└── views/                      # Presentational UI components & charts
    ├── GlucoseChart/           # Recharts continuous glucose monitoring (CGM) line plot
    ├── TIRChart/               # Visualizes target range percentages (stacked / bar views)
    ├── PatientOverview/        # Summarizes current patient metrics and anomalies
    ├── AnomalyAlert/           # Clinician alert notifications with action button
    ├── MultiWeeklyChart/       # Weekly-overlay glucose profile comparison
    ├── GlucoseScatterplot/     # Scientific scatterplot (average, min, max) per day
    ├── CarboDailyChart/        # Carbohydrate intake tracker
    ├── InsulinDailyChart/      # Doses delivered (Basal vs Bolus)
    └── NavBar/                 # Global dashboard navigation bar
```

---

## State Management & Contexts

Global states are propagated through React Context Providers defined under `src/controllers/`:

1. **`GlucoseUnitContext`**:
   - Manages the current glucose concentration unit: standard **`mmol/L`** or **`mg/dL`**.
   - Exposes utility functions (`convert()`, `format()`) to dynamically convert readings across charts and views without altering database telemetry.
2. **`TimeRangeContext`**:
   - Synchronizes time ranges across all charts on the details dashboard.
   - Standard presets: `24h`, `7d`, `2w` (default), `1m`.
3. **`GlucoseRangesContext`**:
   - Stores clinician-defined threshold ranges for Target (Normal), Low, Very Low, High, and Very High levels.
   - Powers the Time in Range (TIR) calculations and out-of-bounds coloring.

---

## View Components

Charts are powered by **Recharts** and styled using vanilla CSS Modules:

- **`GlucoseChart`**: Renders CGM lines with colored threshold boundaries, highlighted target zone, and points of interest.
- **`TIRChart`**: Stacked or simple bar graph showing patient time spent within low, target, and high ranges.
- **`GlucoseScatterplot`**:
  - Displays daily average glucose points.
  - Supports **scientific mode** displaying whisker error bars for min/max ranges, or **capsule mode** showing rounded range pills.
- **`CarboDailyChart`**: Renders daily carbohydrate intake logs.
- **`InsulinDailyChart`**: Compares basal vs bolus insulin intake in a stacked view.
- **`AnomalyAlert`**: Renders clinician-facing alerts for detected missed or late boluses, allowing single-click server-side acknowledgements.
- **`MultiWeeklyChart`**: Overlays several weeks of data on a single 7-day scale to identify recurring weekly trends.
