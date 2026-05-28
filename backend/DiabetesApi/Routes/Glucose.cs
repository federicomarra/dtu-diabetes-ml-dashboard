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
    /// Get glucose readings for a patient within an optional time range.
    /// </summary>
    /// <param name="patientId">Patient ID.</param>
    /// <param name="start">ISO datetime string (optional).</param>
    /// <param name="end">ISO datetime string (optional).</param>
    /// <param name="limit">Maximum number of results (default 500).</param>
    [HttpGet("{patientId:int}")]
    [ProducesResponseType(typeof(GlucosesResponse), StatusCodes.Status200OK)]
    public async Task<IActionResult> GetGlucoseReadings(
        int patientId,
        [FromQuery] string? start = null,
        [FromQuery] string? end   = null,
        [FromQuery] int limit     = 14*24*60)    // two weeks in minutes
    {
        var query = db.Glucoses.Where(r => r.PatientId == patientId);

        if (start is not null)
            query = query.Where(r => r.Timestamp >= DateTime.Parse(start).ToUniversalTime());
        if (end is not null)
            query = query.Where(r => r.Timestamp <= DateTime.Parse(end).ToUniversalTime());

        var readings = await query
            .OrderByDescending(r => r.Timestamp)
            .Take(limit)
            .ToListAsync();

        return Ok(new GlucosesResponse(
            patientId,
            readings.Select(ToDto),
            readings.Count
        ));
    }

    /// <summary>Get time-in-range (TIR) statistics for a patient.</summary>
    /// <param name="patientId">Patient ID.</param>
    /// <param name="ranges">Custom glucose threshold ranges (optional).</param>
    /// <param name="start">ISO datetime string (optional).</param>
    /// <param name="end">ISO datetime string (optional).</param>
    [HttpGet("{patientId:int}/tir")]
    [ProducesResponseType(typeof(TirResponse), StatusCodes.Status200OK)]
    public async Task<IActionResult> GetTimeInRange(
        int patientId,
        [FromQuery] ranges ranges,
        [FromQuery] string? start = null,
        [FromQuery] string? end   = null)
    {
        DateTime? startDt = start is not null ? DateTime.Parse(start).ToUniversalTime() : null;
        DateTime? endDt   = end   is not null ? DateTime.Parse(end).ToUniversalTime()   : null;

        var tir = await glucoseService.CalculateTimeInRangeAsync(patientId, ranges, startDt, endDt);
        return Ok(tir);
    }

    /// <summary>Get the most recent glucose reading for a patient.</summary>
    [HttpGet("{patientId:int}/latest")]
    [ProducesResponseType(typeof(GlucoseReadingDto), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> GetLatestReading(int patientId)
    {
        var reading = await db.Glucoses
            .Where(r => r.PatientId == patientId)
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
}
