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
    /// Returns percentage of readings in each clinical zone, plus the
    /// actual temporal span (in fractional days) covered by the queried readings.
    /// When <paramref name="start"/> / <paramref name="end"/> are supplied the span
    /// is derived from the min/max timestamps of the matching readings.
    /// </summary>
    public async Task<TirResponse> CalculateTimeInRangeAsync(
        int patientId,
        ranges? ranges = null,
        DateTime? start = null,
        DateTime? end = null,
        string? last = null)
    {
        var (defaultVl, defaultL, defaultH, defaultVh) = GetThresholds();
        var thresholds = (
            VeryLow: ranges?.VeryLow ?? defaultVl,
            Low: ranges?.Low ?? defaultL,
            High: ranges?.High ?? defaultH,
            VeryHigh: ranges?.VeryHigh ?? defaultVh
        );

        var query = db.Glucoses
            .Where(r => r.PatientId == patientId);

        if (start.HasValue) {
            query = query.Where(r => r.Timestamp >= start.Value);
        }
        if (end.HasValue) {
            query = query.Where(r => r.Timestamp <= end.Value);
        }

        if (!start.HasValue && !end.HasValue && last is null) {
            last = "2w";
        }

        if (last is not null) {
            var latestTimestamp = await db.Glucoses
                .Where(r => r.PatientId == patientId)
                .Select(r => (DateTime?)r.Timestamp)
                .MaxAsync();
            
            var baseTime = latestTimestamp.HasValue
                ? DateTime.SpecifyKind(latestTimestamp.Value, DateTimeKind.Utc)
                : DateTime.UtcNow;

            if (last.EndsWith("h") && int.TryParse(last.Substring(0, last.Length - 1), out int hours))
            {
                query = query.Where(r => r.Timestamp >= baseTime.AddHours(-hours));
            }
            else if (last.EndsWith("d") && int.TryParse(last.Substring(0, last.Length - 1), out int days))
            {
                query = query.Where(r => r.Timestamp >= baseTime.AddDays(-days));
            }
            else if (last.EndsWith("w") && int.TryParse(last.Substring(0, last.Length - 1), out int weeks))
            {
                query = query.Where(r => r.Timestamp >= baseTime.AddDays(-weeks * 7));
            }
            else if (last.EndsWith("m") && int.TryParse(last.Substring(0, last.Length - 1), out int months))
            {
                query = query.Where(r => r.Timestamp >= baseTime.AddMonths(-months));
            }
        }

        // Project both the glucose value and the timestamp so we can compute
        // the actual time span covered by this set of readings.
        var rows = await query
            .Select(r => new { r.GlucoseMmoll, r.Timestamp })
            .ToListAsync();

        int total = rows.Count;

        if (total == 0)
            return new TirResponse(patientId, 0, 0, 0, 0, 0, 0);

        // Temporal span: difference between the earliest and latest reading.
        DateTime minTs = rows.Min(r => r.Timestamp);
        DateTime maxTs = rows.Max(r => r.Timestamp);
        int temporalSpanDays = (int)(maxTs - minTs).TotalDays + 1;

        var values = rows.Select(r => r.GlucoseMmoll).ToList();

        int veryLowCount  = values.Count(v => v < thresholds.VeryLow);
        int lowCount      = values.Count(v => v >= thresholds.VeryLow && v < thresholds.Low);
        int inRangeCount  = values.Count(v => v >= thresholds.Low && v <= thresholds.High);
        int highCount     = values.Count(v => v > thresholds.High && v <= thresholds.VeryHigh);
        int veryHighCount = values.Count(v => v > thresholds.VeryHigh);

        return new TirResponse(
            patientId,
            temporalSpanDays,
            (float)Math.Round(veryLowCount  / (double)total * 100, 1),
            (float)Math.Round(lowCount      / (double)total * 100, 1),
            (float)Math.Round(inRangeCount  / (double)total * 100, 1),
            (float)Math.Round(highCount     / (double)total * 100, 1),
            (float)Math.Round(veryHighCount / (double)total * 100, 1)
        );
    }
}
