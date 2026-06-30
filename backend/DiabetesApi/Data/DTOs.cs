namespace DiabetesApi.Data;

// DTOs =  Data Transfer Objects

// ── Patients ─────────────────────────────────────────────────────────────────

public record CreatePatientRequest(
    string ExternalId,
    string Name,
    string? DateOfBirth    // ISO date string yyyy-MM-dd
);

public record PatientDto(
    int Id,
    string ExternalId,
    string Name,
    int Age
);

public record PaginatedPatientsResponse(
    IEnumerable<PatientDto> Patients,
    int Total,
    int Page,
    int Pages
);

// ── Glucose ───────────────────────────────────────────────────────────────────

public record GlucoseReadingDto(
    int Id,
    int PatientId,
    string Timestamp,
    float GlucoseMmoll,
    string Source,
    string Status
);

public record GlucosesResponse(
    int PatientId,
    IEnumerable<GlucoseReadingDto> Readings,
    int Count
);

public record TirResponse(
    int PatientId,
    int TemporalSpanDays,
    float VeryLowPct,
    float LowPct,
    float InRangePct,
    float HighPct,
    float VeryHighPct
);

public record GlucoseRanges(
    double? VeryLow = null,
    double? Low = null,
    double? High = null,
    double? VeryHigh = null
);

public record HbA1cResponse(
    int PatientId,
    double Percent,      // e.g. 6.5 (%)
    double MmolPerMol    // e.g. 48  (IFCC mmol/mol)
);

public record GmiResponse(
    int PatientId,
    double Gmi           // e.g. 6.8 (%)
);

/// <summary>Daily aggregated glucose stats — one entry per calendar day (UTC).</summary>
public record DailyGlucosePoint(
    string Date,    // "yyyy-MM-dd"
    double Average, // mmol/L daily average
    double Min,     // mmol/L daily minimum
    double Max      // mmol/L daily maximum
);

public record ScatterplotResponse(
    int PatientId,
    IEnumerable<DailyGlucosePoint> Points,
    int Count
);

// ── Anomalies ─────────────────────────────────────────────────────────────────

public record AnomalyDetectionDto(
    int Id,
    int PatientId,
    int? GlucoseReadingId,
    string AnomalyType,
    float Confidence,
    string? Description,
    bool IsAcknowledged,
    float? Severity = null,        // σ above patient baseline; the frontend slider filters on this
    string? DetectedAt = null      // ISO; anomaly window start
);

public record AnomaliesResponse(
    int PatientId,
    IEnumerable<AnomalyDetectionDto> Anomalies,
    int Count
);

// ── ML inference service (POST $ML_URL/infer) ──────────────────────────────────
// Serialized/deserialized with snake_case (set in MlInferenceService), matching
// ml/docs/ML_INFERENCE_CONTRACT.md. Detector-only: we assemble the 3 channels from
// glucoses+insulins+meals and send only `histories[]`; meals[]/boluses[] (the
// missed/late rule stream) are omitted, so anomalies are detector-surfaced.

// One per-timestamp row of the 3 model channels, assembled from glucoses+insulins+meals.
// NOT the `histories` DB table (that's the training-input table) — only the JSON key is
// "histories", which is what the ML /infer contract expects.
public record MlChannelRow(
    string Timestamp,
    float? GlucoseMmoll,           // null where only an insulin/meal event exists at this minute
    float? InsulinU,
    float? ChoGrams                // ANNOUNCED carbs (from the meals table = logged-at-bolus)
);

public record MlInferRequest(
    int PatientId,
    float ThresholdK,              // low (e.g. 2.0) so ML returns everything; frontend filters later
    IEnumerable<MlChannelRow> Histories     // JSON key "histories" (ML contract); rows built from event tables
);

public record MlAnomaly(
    string Start,
    string End,
    int StartMinute,
    int DurationMin,
    string AnomalyType,            // "missed_bolus" | "late_bolus" (CHECK-safe)
    string Description,
    bool RuleConfirmed,
    float Severity,                // σ above this patient's baseline
    float AnomalyStrength,         // 0–100 magnitude bar (NOT a probability)
    float Score
);

public record MlInferResponse(
    int PatientId,
    int NWindows,
    IEnumerable<MlAnomaly> Anomalies
);

// ── Histories ─────────────────────────────────────────────────────────────────

public record HistoryDto(
    int Id,
    int PatientId,
    string Timestamp,
    float? Glucose,
    float? Insulin,
    float? Meal
);

public record HistoriesResponse(
    int PatientId,
    IEnumerable<HistoryDto> Histories,
    int Count
);

// ── Insulins ──────────────────────────────────────────────────────────────────

public record InsulinDto(
    int Id,
    int PatientId,
    string Timestamp,
    float Units,
    string EventType
);

public record InsulinsResponse(
    int PatientId,
    IEnumerable<InsulinDto> Insulins,
    int Count
);

// ── Meals ─────────────────────────────────────────────────────────────────────

public record MealDto(
    int Id,
    int PatientId,
    string Timestamp,
    float Carbs,
    string? MealType
);

public record MealsResponse(
    int PatientId,
    IEnumerable<MealDto> Meals,
    int Count
);
