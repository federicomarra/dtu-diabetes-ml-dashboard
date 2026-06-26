using Microsoft.AspNetCore.Mvc;
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
        [FromQuery] int id,
        [FromQuery] string? start = null,
        [FromQuery] string? end   = null,
        [FromQuery] string? last = null)
    {
        var query = db.Glucoses.Where(r => r.PatientId == id);

        if (start is not null) {
            query = query.Where(r => r.Timestamp >= DateTime.Parse(start).ToUniversalTime());
        }
        if (end is not null) {
            query = query.Where(r => r.Timestamp <= DateTime.Parse(end).ToUniversalTime());
        }

        if (start is null && end is null && last is null) {
            last = "2w";
        }

        if (last is not null) {
            var latestTimestamp = await db.Glucoses
                .Where(r => r.PatientId == id)
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
            else
            {
                return BadRequest(new { error = "Invalid last parameter format. Use e.g. 24h, 7d, 2w, 1m." });
            }
        }

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
        [FromQuery] int id,
        [FromQuery] GlucoseRanges glucoseRanges,
        [FromQuery] string? start = null,
        [FromQuery] string? end   = null,
        [FromQuery] string? last = null)
    {
        if (last is not null && !last.EndsWith("h") && !last.EndsWith("d") && !last.EndsWith("w") && !last.EndsWith("m")) {
            return BadRequest(new { error = "Invalid last parameter format. Use e.g. 24h, 7d, 2w, 1m." });
        }

        DateTime? startDt = start is not null ? DateTime.Parse(start).ToUniversalTime() : null;
        DateTime? endDt   = end   is not null ? DateTime.Parse(end).ToUniversalTime()   : null;

        var tir = await glucoseService.CalculateTimeInRangeAsync(id, glucoseRanges, startDt, endDt, last);
        return Ok(tir);
    }

    /// <summary>Get the most recent glucose reading for a patient.</summary>
    [HttpGet("latest")]
    [ProducesResponseType(typeof(GlucoseReadingDto), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> GetLatestReading([FromQuery] int id)
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
        [FromQuery] int id,
        [FromQuery] string? start = null,
        [FromQuery] string? end   = null,
        [FromQuery] string? last = null)
    {
        var query = db.Glucoses.Where(r => r.PatientId == id);

        if (start is not null) {
            query = query.Where(r => r.Timestamp >= DateTime.Parse(start).ToUniversalTime());
        }
        if (end is not null) {
            query = query.Where(r => r.Timestamp <= DateTime.Parse(end).ToUniversalTime());
        }

        if (start is null && end is null && last is null) {
            last = "2w";
        }

        if (last is not null) {
            var latestTimestamp = await db.Glucoses
                .Where(r => r.PatientId == id)
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
            else
            {
                return BadRequest(new { error = "Invalid last parameter format. Use e.g. 24h, 7d, 2w, 1m." });
            }
        }

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
        [FromQuery] int id,
        [FromQuery] string? start = null,
        [FromQuery] string? end   = null,
        [FromQuery] string? last = null)
    {
        if (last is not null && !last.EndsWith("h") && !last.EndsWith("d") && !last.EndsWith("w") && !last.EndsWith("m"))
            return BadRequest(new { error = "Invalid last parameter format. Use e.g. 24h, 7d, 2w, 1m." });

        DateTime? startDt = start is not null ? DateTime.Parse(start).ToUniversalTime() : null;
        DateTime? endDt   = end   is not null ? DateTime.Parse(end).ToUniversalTime()   : null;

        var result = await glucoseService.CalculateHbA1cAsync(id, startDt, endDt, last);
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
        [FromQuery] int id,
        [FromQuery] string? start = null,
        [FromQuery] string? end   = null,
        [FromQuery] string? last = null)
    {
        if (last is not null && !last.EndsWith("h") && !last.EndsWith("d") && !last.EndsWith("w") && !last.EndsWith("m"))
            return BadRequest(new { error = "Invalid last parameter format. Use e.g. 24h, 7d, 2w, 1m." });

        DateTime? startDt = start is not null ? DateTime.Parse(start).ToUniversalTime() : null;
        DateTime? endDt   = end   is not null ? DateTime.Parse(end).ToUniversalTime()   : null;

        var result = await glucoseService.CalculateGmiAsync(id, startDt, endDt, last);
        if (result is null)
            return NotFound(new { error = "No readings found for the specified patient and time window." });

        return Ok(result);
    }
}
