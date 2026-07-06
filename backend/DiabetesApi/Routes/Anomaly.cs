using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.ModelBinding;
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
    // frontend's threshold slider decide what to show at read time (see GET minSeverity).
    private const float DetectThresholdK = 2.0f;

    /// <summary>
    /// Get detected anomalies for a patient, optionally filtered by time window.
    /// Severity filtering is handled client-side via the sensitivity slider.
    /// </summary>
    /// <param name="id">Patient ID.</param>
    /// <param name="start">ISO datetime — only anomalies whose detected_at ≥ start (optional).</param>
    /// <param name="end">ISO datetime — only anomalies whose detected_at ≤ end (optional).</param>
    /// <param name="last">Last time period (e.g. "24h", "7d", "2w", "1m"), measured back from the latest glucose reading (optional).</param>
    [HttpGet]
    [ProducesResponseType(typeof(AnomaliesResponse), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> GetAnomalies(
        [FromQuery, BindRequired] int id,
        [FromQuery] string? start = null,
        [FromQuery] string? end = null,
        [FromQuery] string? last = null)
    {
        var query = db.Anomalies.Where(a => a.PatientId == id);

        // No temporal parameters means no filtering.
        if (start is null && end is null && last is null)
        {
            // Do not filter temporally.
        }
        else if (start is not null && end is not null)
        {
            var s = DateTime.Parse(start).ToUniversalTime();
            var e = DateTime.Parse(end).ToUniversalTime();
            query = query.Where(a => a.DetectedAt >= s && a.DetectedAt <= e);
        }
        else
        {
            var range = await TimeRangeUtils.ResolveTimeRangeAsync(
                last:  last,
                start: start,
                end:   end,
                getLatestTimestamp: () => db.Glucoses
                    .Where(g => g.PatientId == id)
                    .Select(g => (DateTime?)g.Timestamp)
                    .MaxAsync());

            if (range is null)
                return BadRequest(new { error = "Invalid last parameter format. Use e.g. 24h, 7d, 2w, 1m." });

            query = query.Where(a => a.DetectedAt >= range.Value.start && a.DetectedAt <= range.Value.end);
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
    /// Run ML detection for a patient over a window and store the results.
    /// Assembles the 3 glucoses+insulins+meals and POSTs to the ML service,
    /// then gets anomalies and updates the database.
    /// </summary>
    /// <param name="id">Patient ID</param>
    /// <param name="start">ISO datetime window start (optional).</param>
    /// <param name="end">ISO datetime window end (optional; defaults to the latest glucose reading)</param>
    /// <param name="last">Last time period (e.g. "24h", "7d", "2w", "1m") back from end (optional; defaults to 2w if no start)</param>
    [HttpPost("detect")]
    [ProducesResponseType(typeof(AnomaliesResponse), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType(StatusCodes.Status503ServiceUnavailable)]
    public async Task<IActionResult> Detect(
        [FromQuery, BindRequired] int id,
        [FromQuery] string? start = null,
        [FromQuery] string? end = null,
        [FromQuery] string? last = null)
    {
        if (!await db.Patients.AnyAsync(p => p.Id == id))
            return NotFound(new { error = "Patient not found" });

        DateTime startDt, endDt;

        if (start is not null && end is not null)
        {
            startDt = DateTime.Parse(start).ToUniversalTime();
            endDt = DateTime.Parse(end).ToUniversalTime();
        }
        else
        {
            var latest = await db.Glucoses.Where(g => g.PatientId == id)
                .Select(g => (DateTime?)g.Timestamp).MaxAsync();
            
            if (latest is null && end is null)
                return Ok(new AnomaliesResponse(id, [], 0));

            var range = await TimeRangeUtils.ResolveTimeRangeAsync(
                last: last,
                start: start,
                end: end,
                getLatestTimestamp: () => Task.FromResult(latest));

            if (range is null)
                return BadRequest(new { error = "Invalid last parameter format. Use e.g. 24h, 7d, 2w, 1m." });

            startDt = range.Value.start;
            endDt = range.Value.end;
        }

        if (!await ml.IsHealthyAsync())
            return StatusCode(StatusCodes.Status503ServiceUnavailable,
                new { error = "ML service not ready (model still loading). Try again shortly." });

        var rows = await BuildChannelRows(id, startDt, endDt);
        if (rows.Count == 0) return Ok(new AnomaliesResponse(id, [], 0));

        var result = await ml.InferAsync(new MlInferRequest(id, DetectThresholdK, rows));
        var returned = result?.Anomalies?.ToList() ?? [];

        // Overwrite this window: delete AFTER a successful ML call (so a failure never loses
        // the old rows), then insert everything returned (no pre-filter — store all).
        var stale = db.Anomalies.Where(a =>
            a.PatientId == id && a.DetectedAt >= startDt && a.DetectedAt <= endDt);
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
        await db.SaveChangesAsync();

        return Ok(new AnomaliesResponse(id, inserted.Select(ToDto), inserted.Count));
    }

    /// <summary>Mark an anomaly as acknowledged by a clinician</summary>
    /// <param name="patientId">Patient ID — the anomaly must belong to this patient</param>
    /// <param name="anomalyId">Anomaly ID to acknowledge.</param>
    [HttpPost("acknowledge")]
    [ProducesResponseType(typeof(AnomalyDetectionDto), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> AcknowledgeAnomaly(
        [FromQuery, BindRequired] int patientId,
        [FromQuery, BindRequired] int anomalyId)
    {
        var anomaly = await db.Anomalies.FindAsync(anomalyId);
        if (anomaly is null || anomaly.PatientId != patientId) return NotFound();

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
    private async Task<List<MlChannelRow>> BuildChannelRows(int id, DateTime startDt, DateTime endDt)
    {
        var glucoses = await db.Glucoses
            .Where(g => g.PatientId == id && g.Timestamp >= startDt && g.Timestamp <= endDt)
            .Select(g => new { g.Timestamp, g.GlucoseMmoll }).ToListAsync();
        var insulins = await db.Insulins
            .Where(i => i.PatientId == id && i.Timestamp >= startDt && i.Timestamp <= endDt)
            .Select(i => new { i.Timestamp, i.Units, i.EventType }).ToListAsync();
        var meals = await db.Meals
            .Where(m => m.PatientId == id && m.Timestamp >= startDt && m.Timestamp <= endDt)
            .Select(m => new { m.Timestamp, m.Carbs }).ToListAsync();

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

        // Plain second-resolution ISO (no sub-second): Python 3.10 datetime.fromisoformat
        // (used by the ML loader) rejects the 7-digit fraction that "O" emits.
        return byTime.Select(kv => new MlChannelRow(
            kv.Key.ToString("yyyy-MM-ddTHH:mm:ss"), kv.Value.glu, kv.Value.ins, kv.Value.cho)).ToList();
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
