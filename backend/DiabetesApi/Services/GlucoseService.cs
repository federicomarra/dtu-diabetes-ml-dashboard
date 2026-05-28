using System;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using Microsoft.EntityFrameworkCore;
using DiabetesApi.Data;

namespace DiabetesApi.Services;

/// <summary>Business logic for glucose data computations.</summary>
public class GlucoseService(AppDbContext db)
{
    private (double VeryLow, double Low, double High, double VeryHigh) GetThresholds()
    {
        // Clinical glucose target ranges (mmol/L) — defaults matching standard clinical zones
        double veryLow  = 3.0;
        double low      = 3.9;
        double high     = 10.0;
        double veryHigh = 13.9;

        try
        {
            // Search paths for glucose-config.json (both local and container/test environments)
            var searchPaths = new[]
            {
                "glucose-config.json",
                Path.Combine(AppContext.BaseDirectory, "glucose-config.json"),
                Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "..", "frontend", "glucose-config.json"),
                Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "frontend", "glucose-config.json"),
                "../frontend/glucose-config.json",
                "../../frontend/glucose-config.json"
            };

            string? foundPath = null;
            foreach (var path in searchPaths)
            {
                if (File.Exists(path))
                {
                    foundPath = path;
                    break;
                }
            }

            if (foundPath != null)
            {
                var jsonContent = File.ReadAllText(foundPath);
                using var doc = System.Text.Json.JsonDocument.Parse(jsonContent);
                var root = doc.RootElement;

                if (root.TryGetProperty("VERY_LOW_THRESHOLD", out var vl)) veryLow = vl.GetDouble();
                if (root.TryGetProperty("LOW_THRESHOLD", out var l)) low = l.GetDouble();
                if (root.TryGetProperty("HIGH_THRESHOLD", out var h)) high = h.GetDouble();
                if (root.TryGetProperty("VERY_HIGH_THRESHOLD", out var vh)) veryHigh = vh.GetDouble();
            }
        }
        catch
        {
            // Fail gracefully to clinical defaults if config file is unreadable
        }

        return (veryLow, low, high, veryHigh);
    }

    /// <summary>
    /// Calculate Time-In-Range (TIR) statistics for a patient.
    /// Returns percentage of readings in each clinical zone.
    /// </summary>
    public async Task<TirResponse> CalculateTimeInRangeAsync(
        int patientId,
        DateTime? start = null,
        DateTime? end = null)
    {
        var thresholds = GetThresholds();

        var query = db.Glucoses
            .Where(r => r.PatientId == patientId);

        if (start.HasValue)
            query = query.Where(r => r.Timestamp >= start.Value);
        if (end.HasValue)
            query = query.Where(r => r.Timestamp <= end.Value);

        var readings = await query.Select(r => r.GlucoseMmoll).ToListAsync();
        int total = readings.Count;

        if (total == 0)
            return new TirResponse(patientId, 0, 0, 0, 0, 0, 0);

        int veryLowCount  = readings.Count(v => v < thresholds.VeryLow);
        int lowCount      = readings.Count(v => v >= thresholds.VeryLow && v < thresholds.Low);
        int inRangeCount  = readings.Count(v => v >= thresholds.Low && v <= thresholds.High);
        int highCount     = readings.Count(v => v > thresholds.High && v <= thresholds.VeryHigh);
        int veryHighCount = readings.Count(v => v > thresholds.VeryHigh);

        return new TirResponse(
            patientId,
            total,
            (float)Math.Round(veryLowCount  / (double)total * 100, 1),
            (float)Math.Round(lowCount      / (double)total * 100, 1),
            (float)Math.Round(inRangeCount  / (double)total * 100, 1),
            (float)Math.Round(highCount     / (double)total * 100, 1),
            (float)Math.Round(veryHighCount / (double)total * 100, 1)
        );
    }
}
