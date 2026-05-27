using DiabetesApi.Data;
using DiabetesApi.DTOs;
using Microsoft.EntityFrameworkCore;

namespace DiabetesApi.Services;

/// <summary>Business logic for glucose data computations.</summary>
public class GlucoseService(AppDbContext db)
{
    // Clinical glucose target ranges (mmol/L) — matches the Python service
    private const double VeryLow  = 3.0;
    private const double Low      = 3.9;
    private const double High     = 10.0;
    private const double VeryHigh = 13.9;

    /// <summary>
    /// Calculate Time-In-Range (TIR) statistics for a patient.
    /// Returns percentage of readings in each clinical zone.
    /// </summary>
    public async Task<TirResponse> CalculateTimeInRangeAsync(
        int patientId,
        DateTime? start = null,
        DateTime? end = null)
    {
        var query = db.GlucoseReadings
            .Where(r => r.PatientId == patientId);

        if (start.HasValue)
            query = query.Where(r => r.Timestamp >= start.Value);
        if (end.HasValue)
            query = query.Where(r => r.Timestamp <= end.Value);

        var readings = await query.Select(r => r.GlucoseMmoll).ToListAsync();
        int total = readings.Count;

        if (total == 0)
            return new TirResponse(patientId, 0, 0, 0, 0, 0, 0);

        int veryLowCount  = readings.Count(v => v < VeryLow);
        int lowCount      = readings.Count(v => v >= VeryLow && v < Low);
        int inRangeCount  = readings.Count(v => v >= Low && v <= High);
        int highCount     = readings.Count(v => v > High && v <= VeryHigh);
        int veryHighCount = readings.Count(v => v > VeryHigh);

        return new TirResponse(
            patientId,
            total,
            Math.Round(veryLowCount  / (double)total * 100, 1),
            Math.Round(lowCount      / (double)total * 100, 1),
            Math.Round(inRangeCount  / (double)total * 100, 1),
            Math.Round(highCount     / (double)total * 100, 1),
            Math.Round(veryHighCount / (double)total * 100, 1)
        );
    }
}
