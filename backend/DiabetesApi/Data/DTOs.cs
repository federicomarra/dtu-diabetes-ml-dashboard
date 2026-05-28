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

public record ranges(
    double? VeryLow = null,
    double? Low = null,
    double? High = null,
    double? VeryHigh = null
);

// ── Anomalies ─────────────────────────────────────────────────────────────────

public record AnomalyDetectionDto(
    int Id,
    int PatientId,
    int? GlucoseReadingId,
    string AnomalyType,
    float Confidence,
    string? Description,
    bool IsAcknowledged
);

public record AnomaliesResponse(
    int PatientId,
    IEnumerable<AnomalyDetectionDto> Anomalies,
    int Count
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
