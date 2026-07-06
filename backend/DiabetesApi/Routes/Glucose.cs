using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.ModelBinding;
using Microsoft.EntityFrameworkCore;
using DiabetesApi.Data;
using DiabetesApi.Models;
using DiabetesApi.Services;

namespace DiabetesApi.Routes;

/// <summary>Glucose readings and statistics.</summary>
[ApiController]
[Route("api/glucose")]
[Produces("application/json")]
public class GlucoseController(AppDbContext db, GlucoseService glucoseService) : ControllerBase
{
    /// <summary>
    /// Get glucose readings for a patient within an optional time range or duration.
    /// </summary>
    /// <param name="id">Patient ID</param>
    /// <param name="start">ISO datetime string (optional)</param>
    /// <param name="end">ISO datetime string (optional)</param>
    /// <param name="last">Last time period (e.g. "24h", "7d", "2w", "1m") (optional, default '2w' if no start/end specified)</param>
    [HttpGet]
    [ProducesResponseType(typeof(GlucosesResponse), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> GetGlucoseReadings(
        [FromQuery, BindRequired] int id,
        [FromQuery] string? start = null,
        [FromQuery] string? end   = null,
        [FromQuery] string? last = null)
    {
        var query = db.Glucoses.Where(r => r.PatientId == id);

        DateTime s, e;

        // Short-circuit: both anchors explicit — apply directly and skip range resolution.
        if (start is not null && end is not null)
        {
            s = DateTime.Parse(start).ToUniversalTime();
            e = DateTime.Parse(end).ToUniversalTime();
        }
        else
        {
            var range = await TimeRangeUtils.ResolveTimeRangeAsync(
                last:  last,
                start: start,
                end:   end,
                getLatestTimestamp: () => db.Glucoses
                    .Where(r => r.PatientId == id)
                    .Select(r => (DateTime?)r.Timestamp)
                    .MaxAsync());

            if (range is null)
                return BadRequest(new { error = "Invalid last parameter format. Use e.g. 24h, 7d, 2w, 1m." });

            s = range.Value.start;
            e = range.Value.end;
        }

        query = query.Where(r => r.Timestamp >= s && r.Timestamp <= e);

        var readings = await query
            .OrderByDescending(r => r.Timestamp)
            .ToListAsync();

        return Ok(new GlucosesResponse(
            id,
            readings.Select(ToDto),
            readings.Count
        ));
    }

    /// <summary>Get time-in-range (TIR) statistics for a patient.</summary>
    /// <param name="id">Patient ID.</param>
    /// <param name="glucoseRanges">Custom glucose threshold ranges (optional).</param>
    /// <param name="start">ISO datetime string (optional).</param>
    /// <param name="end">ISO datetime string (optional).</param>
    /// <param name="last">Last time period (e.g. "24h", "7d", "2w", "1m") (optional, default '2w' if no start/end specified).</param>
    [HttpGet("tir")]
    [ProducesResponseType(typeof(TirResponse), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> GetTimeInRange(
        [FromQuery, BindRequired] int id,
        [FromQuery] GlucoseRanges glucoseRanges,
        [FromQuery] string? start = null,
        [FromQuery] string? end   = null,
        [FromQuery] string? last = null)
    {
        DateTime? startDt = null;
        DateTime? endDt = null;

        // Short-circuit: both anchors explicit.
        if (start is not null && end is not null)
        {
            startDt = DateTime.Parse(start).ToUniversalTime();
            endDt = DateTime.Parse(end).ToUniversalTime();
        }
        else
        {
            var range = await TimeRangeUtils.ResolveTimeRangeAsync(
                last:  last,
                start: start,
                end:   end,
                getLatestTimestamp: () => db.Glucoses
                    .Where(r => r.PatientId == id)
                    .Select(r => (DateTime?)r.Timestamp)
                    .MaxAsync());

            if (range is null)
                return BadRequest(new { error = "Invalid last parameter format. Use e.g. 24h, 7d, 2w, 1m." });

            startDt = range.Value.start;
            endDt = range.Value.end;
        }

        var tir = await glucoseService.CalculateTimeInRangeAsync(id, glucoseRanges, startDt, endDt);
        return Ok(tir);
    }

    /// <summary>Get the most recent glucose reading for a patient.</summary>
    [HttpGet("latest")]
    [ProducesResponseType(typeof(GlucoseReadingDto), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> GetLatestReading([FromQuery, BindRequired] int id)
    {
        var reading = await db.Glucoses
            .Where(r => r.PatientId == id)
            .OrderByDescending(r => r.Timestamp)
            .FirstOrDefaultAsync();

        if (reading is null)
            return NotFound(new { error = "No readings found" });

        return Ok(ToDto(reading));
    }

    private static GlucoseReadingDto ToDto(Glucose r) => new(
        r.Id,
        r.PatientId,
        r.Timestamp.ToString("O"),
        (float)r.GlucoseMmoll,
        r.Source,
        r.Status
    );


    /// <summary>
    /// Get average glucose reading for a patient within an optional time range or duration.
    /// </summary>
    /// <param name="id">Patient ID</param>
    /// <param name="start">ISO datetime string (optional)</param>
    /// <param name="end">ISO datetime string (optional)</param>
    /// <param name="last">Last time period (e.g. "24h", "7d", "2w", "1m") (optional, default '2w' if no start/end specified)</param>
    [HttpGet("average")]
    [ProducesResponseType(typeof(double), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> GetAverageReading(
        [FromQuery, BindRequired] int id,
        [FromQuery] string? start = null,
        [FromQuery] string? end   = null,
        [FromQuery] string? last = null)
    {
        var query = db.Glucoses.Where(r => r.PatientId == id);

        DateTime s, e;

        // Short-circuit: both anchors explicit.
        if (start is not null && end is not null)
        {
            s = DateTime.Parse(start).ToUniversalTime();
            e = DateTime.Parse(end).ToUniversalTime();
        }
        else
        {
            var range = await TimeRangeUtils.ResolveTimeRangeAsync(
                last:  last,
                start: start,
                end:   end,
                getLatestTimestamp: () => db.Glucoses
                    .Where(r => r.PatientId == id)
                    .Select(r => (DateTime?)r.Timestamp)
                    .MaxAsync());

            if (range is null)
                return BadRequest(new { error = "Invalid last parameter format. Use e.g. 24h, 7d, 2w, 1m." });

            s = range.Value.start;
            e = range.Value.end;
        }

        query = query.Where(r => r.Timestamp >= s && r.Timestamp <= e);

        var average = await query
            .Select(r => (double?)r.GlucoseMmoll)
            .AverageAsync();

        if (average is null) {
            return NotFound(new { error = "No readings found" });
        }

        return Ok(average.Value);
    }

    /// <summary>
    /// Get estimated HbA1c for a patient within an optional time range or duration.
    /// </summary>
    /// <param name="id">Patient ID</param>
    /// <param name="start">ISO datetime string (optional)</param>
    /// <param name="end">ISO datetime string (optional)</param>
    /// <param name="last">Last time period (e.g. "24h", "7d", "2w", "1m") (optional, default '2w' if no start/end specified)</param>
    [HttpGet("hba1c")]
    [ProducesResponseType(typeof(HbA1cResponse), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> GetHbA1c(
        [FromQuery, BindRequired] int id,
        [FromQuery] string? start = null,
        [FromQuery] string? end   = null,
        [FromQuery] string? last = null)
    {
        DateTime? startDt = null;
        DateTime? endDt = null;

        // Short-circuit: both anchors explicit.
        if (start is not null && end is not null)
        {
            startDt = DateTime.Parse(start).ToUniversalTime();
            endDt = DateTime.Parse(end).ToUniversalTime();
        }
        else
        {
            var range = await TimeRangeUtils.ResolveTimeRangeAsync(
                last:  last,
                start: start,
                end:   end,
                getLatestTimestamp: () => db.Glucoses
                    .Where(r => r.PatientId == id)
                    .Select(r => (DateTime?)r.Timestamp)
                    .MaxAsync());

            if (range is null)
                return BadRequest(new { error = "Invalid last parameter format. Use e.g. 24h, 7d, 2w, 1m." });

            startDt = range.Value.start;
            endDt = range.Value.end;
        }

        var result = await glucoseService.CalculateHbA1cAsync(id, startDt, endDt);
        if (result is null)
            return NotFound(new { error = "No readings found for the specified patient and time window." });

        return Ok(result);
    }

    /// <summary>
    /// Get Glucose Management Indicator (GMI) for a patient within an optional time range or duration.
    /// </summary>
    /// <param name="id">Patient ID</param>
    /// <param name="start">ISO datetime string (optional)</param>
    /// <param name="end">ISO datetime string (optional)</param>
    /// <param name="last">Last time period (e.g. "24h", "7d", "2w", "1m") (optional, default '2w' if no start/end specified)</param>
    [HttpGet("gmi")]
    [ProducesResponseType(typeof(GmiResponse), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> GetGmi(
        [FromQuery, BindRequired] int id,
        [FromQuery] string? start = null,
        [FromQuery] string? end   = null,
        [FromQuery] string? last = null)
    {
        DateTime? startDt = null;
        DateTime? endDt = null;

        // Short-circuit: both anchors explicit.
        if (start is not null && end is not null)
        {
            startDt = DateTime.Parse(start).ToUniversalTime();
            endDt = DateTime.Parse(end).ToUniversalTime();
        }
        else
        {
            var range = await TimeRangeUtils.ResolveTimeRangeAsync(
                last:  last,
                start: start,
                end:   end,
                getLatestTimestamp: () => db.Glucoses
                    .Where(r => r.PatientId == id)
                    .Select(r => (DateTime?)r.Timestamp)
                    .MaxAsync());

            if (range is null)
                return BadRequest(new { error = "Invalid last parameter format. Use e.g. 24h, 7d, 2w, 1m." });

            startDt = range.Value.start;
            endDt = range.Value.end;
        }

        var result = await glucoseService.CalculateGmiAsync(id, startDt, endDt);
        if (result is null)
            return NotFound(new { error = "No readings found for the specified patient and time window." });

        return Ok(result);
    }

    /// <summary>
    /// Get per-day glucose averages with min/max for a scatterplot, for a patient within an optional time range or duration.
    /// </summary>
    /// <param name="id">Patient ID</param>
    /// <param name="start">ISO datetime string (optional)</param>
    /// <param name="end">ISO datetime string (optional)</param>
    /// <param name="last">Last time period (e.g. "24h", "7d", "2w", "1m") (optional, default '2w' if no start/end specified)</param>
    [HttpGet("scatterplot")]
    [ProducesResponseType(typeof(ScatterplotResponse), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> GetScatterplot(
        [FromQuery, BindRequired] int id,
        [FromQuery] string? start = null,
        [FromQuery] string? end   = null,
        [FromQuery] string? last = null)
    {
        DateTime? startDt = null;
        DateTime? endDt = null;

        // Short-circuit: both anchors explicit.
        if (start is not null && end is not null)
        {
            startDt = DateTime.Parse(start).ToUniversalTime();
            endDt = DateTime.Parse(end).ToUniversalTime();
        }
        else
        {
            var range = await TimeRangeUtils.ResolveTimeRangeAsync(
                last:  last,
                start: start,
                end:   end,
                getLatestTimestamp: () => db.Glucoses
                    .Where(r => r.PatientId == id)
                    .Select(r => (DateTime?)r.Timestamp)
                    .MaxAsync());

            if (range is null)
                return BadRequest(new { error = "Invalid last parameter format. Use e.g. 24h, 7d, 2w, 1m." });

            startDt = range.Value.start;
            endDt = range.Value.end;
        }

        var result = await glucoseService.CalculateScatterplotAsync(id, startDt, endDt);
        if (result is null)
            return NotFound(new { error = "No readings found for the specified patient and time window." });

        return Ok(result);
    }
}
