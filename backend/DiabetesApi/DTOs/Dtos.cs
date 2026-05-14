namespace DiabetesApi.DTOs;

// ── Patients ─────────────────────────────────────────────────────────────────

public record CreatePatientRequest(
    string ExternalId,
    string Name,
    string? DiabetesType,
    string? DateOfBirth,    // ISO date string yyyy-MM-dd
    string? DiagnosisDate   // ISO date string yyyy-MM-dd
);

public record PatientDto(
    int Id,
    string ExternalId,
    string Name,
    string? DateOfBirth,
    string DiabetesType,
    string? DiagnosisDate,
    string? CreatedAt
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
    double GlucoseMmoll,
    string Source,
    string Status
);

public record GlucoseReadingsResponse(
    int PatientId,
    IEnumerable<GlucoseReadingDto> Readings,
    int Count
);

public record TirResponse(
    int PatientId,
    int TotalReadings,
    double VeryLowPct,
    double LowPct,
    double InRangePct,
    double HighPct,
    double VeryHighPct
);

// ── Anomalies ─────────────────────────────────────────────────────────────────

public record AnomalyDetectionDto(
    int Id,
    int PatientId,
    int? GlucoseReadingId,
    string AnomalyType,
    double Confidence,
    string? Description,
    bool IsAcknowledged,
    string? DetectedAt
);

public record AnomaliesResponse(
    int PatientId,
    IEnumerable<AnomalyDetectionDto> Anomalies,
    int Count
);
