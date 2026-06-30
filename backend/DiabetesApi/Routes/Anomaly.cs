using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using DiabetesApi.Data;
using DiabetesApi.Models;
using DiabetesApi.Services;

namespace DiabetesApi.Routes;

/// <summary>Anomaly detection results and acknowledgement.</summary>
[ApiController]
[Route("api/anomaly")]
[Produces("application/json")]
public class Anomaly(AppDbContext db, MlInferenceService ml) : ControllerBase
{
    // Sent to ML so nothing is pre-filtered — we store ALL returned anomalies and let the
    // frontend's threshold slider decide what to show at read time (see GET min_severity).
    private const float DetectThresholdK = 2.0f;

    /// <summary>
    /// Get detected anomalies for a patient, optionally filtered by severity and time window.
    /// </summary>
    /// <param name="id">Patient ID.</param>
    /// <param name="min_severity">Only return anomalies with severity ≥ this (σ; the frontend threshold). At slider minimum → all.</param>
    /// <param name="start">ISO datetime — only anomalies whose detected_at ≥ start (optional).</param>
    /// <param name="end">ISO datetime — only anomalies whose detected_at ≤ end (optional).</param>
    /// <param name="last">Last time period (e.g. "24h", "7d", "2w", "1m"), measured back from the latest glucose reading (optional).</param>
    [HttpGet]
    [ProducesResponseType(typeof(AnomaliesResponse), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> GetAnomalies(
        [FromQuery] int id,
        [FromQuery(Name = "min_severity")] float? minSeverity = null,
        [FromQuery] string? start = null,
        [FromQuery] string? end = null,
        [FromQuery] string? last = null)
    {
        var query = db.Anomalies.Where(a => a.PatientId == id);

        if (minSeverity.HasValue)
            query = query.Where(a => a.Severity >= minSeverity.Value);

        if (start is not null)
        {
            var startDt = DateTime.Parse(start).ToUniversalTime();
            query = query.Where(a => a.DetectedAt >= startDt);
        }
        if (end is not null)
        {
            var endDt = DateTime.Parse(end).ToUniversalTime();
            query = query.Where(a => a.DetectedAt <= endDt);
        }
        if (last is not null)
        {
            var baseTime = await LatestGlucoseTime(id);
            var cutoff = LastCutoff(baseTime, last);
            if (cutoff is null)
                return BadRequest(new { error = "Invalid last parameter format. Use e.g. 24h, 7d, 2w, 1m." });
            query = query.Where(a => a.DetectedAt >= cutoff.Value);
        }

        var anomalies = await query
            .OrderByDescending(a => a.Severity)
            .ToListAsync();

        return Ok(new AnomaliesResponse(
            id,
            anomalies.Select(ToDto),
            anomalies.Count
        ));
    }

    /// <summary>
    /// Run ML detection for a patient over a window and store the results (inference=true path).
    /// Assembles the 3 model channels from glucoses+insulins+meals, POSTs to the ML service,
    /// then overwrites this window's anomalies (delete-after-success → insert all returned).
    /// The frontend reads them back via GET with its chosen min_severity.
    /// </summary>
    /// <param name="id">Patient ID.</param>
    /// <param name="start">ISO datetime window start (optional).</param>
    /// <param name="end">ISO datetime window end (optional; defaults to the latest glucose reading).</param>
    /// <param name="last">Last time period (e.g. "24h", "7d", "2w", "1m") back from end (optional; defaults to 2w if no start).</param>
    [HttpPost("detect")]
    [ProducesResponseType(typeof(AnomaliesResponse), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType(StatusCodes.Status503ServiceUnavailable)]
    public async Task<IActionResult> Detect(
        [FromQuery] int id,
        [FromQuery] string? start = null,
        [FromQuery] string? end = null,
        [FromQuery] string? last = null,
        CancellationToken ct = default)
    {
        if (!await db.Patients.AnyAsync(p => p.Id == id, ct))
            return NotFound(new { error = "Patient not found" });

        // Resolve the window. end defaults to the latest glucose reading; start comes from
        // an explicit start, else `last` back from end, else a 2-week default.
        DateTime? endDt = end is not null ? DateTime.Parse(end).ToUniversalTime() : null;
        DateTime? startDt = start is not null ? DateTime.Parse(start).ToUniversalTime() : null;
        if (endDt is null)
        {
            var latest = await db.Glucoses.Where(g => g.PatientId == id)
                .Select(g => (DateTime?)g.Timestamp).MaxAsync(ct);
            if (latest is null) return Ok(new AnomaliesResponse(id, [], 0));   // no data → nothing to detect
            endDt = DateTime.SpecifyKind(latest.Value, DateTimeKind.Utc);
        }
        if (startDt is null && last is not null)
        {
            startDt = LastCutoff(endDt.Value, last);
            if (startDt is null)
                return BadRequest(new { error = "Invalid last parameter format. Use e.g. 24h, 7d, 2w, 1m." });
        }
        startDt ??= endDt.Value.AddDays(-14);

        if (!await ml.IsHealthyAsync(ct))
            return StatusCode(StatusCodes.Status503ServiceUnavailable,
                new { error = "ML service not ready (model still loading). Try again shortly." });

        var rows = await BuildChannelRows(id, startDt.Value, endDt.Value, ct);
        if (rows.Count == 0) return Ok(new AnomaliesResponse(id, [], 0));

        var result = await ml.InferAsync(new MlInferRequest(id, DetectThresholdK, rows), ct);
        var returned = result?.Anomalies?.ToList() ?? [];

        // Overwrite this window: delete AFTER a successful ML call (so a failure never loses
        // the old rows), then insert everything returned (no pre-filter — store all).
        var stale = db.Anomalies.Where(a =>
            a.PatientId == id && a.DetectedAt >= startDt.Value && a.DetectedAt <= endDt.Value);
        db.Anomalies.RemoveRange(stale);

        var inserted = returned.Select(a => new Models.Anomaly
        {
            PatientId = id,
            AnomalyType = a.AnomalyType,
            Confidence = a.AnomalyStrength / 100.0,   // 0–1 magnitude bar, NOT a probability
            Severity = a.Severity,
            DetectedAt = DateTime.Parse(a.Start).ToUniversalTime(),
            Description = a.Description,
            IsAcknowledged = false,
        }).ToList();
        db.Anomalies.AddRange(inserted);
        await db.SaveChangesAsync(ct);

        return Ok(new AnomaliesResponse(id, inserted.Select(ToDto), inserted.Count));
    }

    /// <summary>Mark an anomaly as acknowledged by a clinician.</summary>
    [HttpPost("{anomalyId:int}/acknowledge")]
    [ProducesResponseType(typeof(AnomalyDetectionDto), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> AcknowledgeAnomaly(int anomalyId)
    {
        var anomaly = await db.Anomalies.FindAsync(anomalyId);
        if (anomaly is null) return NotFound();

        anomaly.IsAcknowledged = true;
        await db.SaveChangesAsync();

        return Ok(ToDto(anomaly));
    }

    // Spreading windows (min) to invert upload_parquet.py's event collapse → per-minute U/min
    // rate, the way the `histories` table held insulin. A bolus event is a few minutes of
    // delivery; a basal event is an HOURLY sum, so it must spread over the whole hour (a 3-min
    // spread would make a ~20× spike). Carbs stay a single-minute value (announced at the bolus).
    private const int BolusSpreadMin = 3;
    private const int BasalSpreadMin = 60;

    /// <summary>
    /// Assemble one ML channel row per distinct minute in the window, merging glucose
    /// (glucoses), insulin RATE (insulins, reconstructed per-minute), and announced carbs
    /// (meals). The ML service builds a 1-minute grid and tolerates sparse/missing channels.
    /// </summary>
    private async Task<List<MlChannelRow>> BuildChannelRows(int id, DateTime startDt, DateTime endDt, CancellationToken ct)
    {
        var glucoses = await db.Glucoses
            .Where(g => g.PatientId == id && g.Timestamp >= startDt && g.Timestamp <= endDt)
            .Select(g => new { g.Timestamp, g.GlucoseMmoll }).ToListAsync(ct);
        var insulins = await db.Insulins
            .Where(i => i.PatientId == id && i.Timestamp >= startDt && i.Timestamp <= endDt)
            .Select(i => new { i.Timestamp, i.Units, i.EventType }).ToListAsync(ct);
        var meals = await db.Meals
            .Where(m => m.PatientId == id && m.Timestamp >= startDt && m.Timestamp <= endDt)
            .Select(m => new { m.Timestamp, m.Carbs }).ToListAsync(ct);

        // Merge by minute. Multiple events on the same minute are summed (insulin/carbs).
        var byTime = new SortedDictionary<DateTime, (float? glu, float? ins, float? cho)>();

        void AddInsulin(DateTime t, float ratePerMin)
        {
            var cur = byTime.GetValueOrDefault(t);
            byTime[t] = (cur.glu, (cur.ins ?? 0) + ratePerMin, cur.cho);
        }

        foreach (var g in glucoses)
        {
            var cur = byTime.GetValueOrDefault(g.Timestamp);
            byTime[g.Timestamp] = ((float)g.GlucoseMmoll, cur.ins, cur.cho);
        }
        foreach (var i in insulins)
        {
            if (i.Units <= 0) continue;   // zero markers (basal stop/resume) carry no dose
            int span = i.EventType == "basal" ? BasalSpreadMin : BolusSpreadMin;
            float perMin = (float)i.Units / span;
            for (int k = 0; k < span; k++)
                AddInsulin(i.Timestamp.AddMinutes(k), perMin);
        }
        foreach (var m in meals)
        {
            var cur = byTime.GetValueOrDefault(m.Timestamp);
            byTime[m.Timestamp] = (cur.glu, cur.ins, (cur.cho ?? 0) + (float)m.Carbs);
        }

        return byTime.Select(kv => new MlChannelRow(
            kv.Key.ToString("O"), kv.Value.glu, kv.Value.ins, kv.Value.cho)).ToList();
    }

    /// <summary>Latest glucose timestamp for the patient (the data's "now"), or UtcNow if none.</summary>
    private async Task<DateTime> LatestGlucoseTime(int patientId)
    {
        var latest = await db.Glucoses.Where(g => g.PatientId == patientId)
            .Select(g => (DateTime?)g.Timestamp).MaxAsync();
        return latest.HasValue ? DateTime.SpecifyKind(latest.Value, DateTimeKind.Utc) : DateTime.UtcNow;
    }

    /// <summary>Parse a "24h"/"7d"/"2w"/"1m" period and subtract it from baseTime. Null if malformed.</summary>
    private static DateTime? LastCutoff(DateTime baseTime, string last)
    {
        if (last.Length < 2 || !int.TryParse(last[..^1], out int n)) return null;
        return last[^1] switch
        {
            'h' => baseTime.AddHours(-n),
            'd' => baseTime.AddDays(-n),
            'w' => baseTime.AddDays(-n * 7),
            'm' => baseTime.AddMonths(-n),
            _   => null,
        };
    }

    private static AnomalyDetectionDto ToDto(Models.Anomaly a) => new(
        a.Id,
        a.PatientId,
        a.GlucoseReadingId,
        a.AnomalyType,
        (float)a.Confidence,
        a.Description,
        a.IsAcknowledged,
        a.Severity is null ? null : (float)a.Severity,
        a.DetectedAt?.ToString("O")
    );
}
