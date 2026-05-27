using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using DiabetesApi.Data;
using DiabetesApi.DTOs;
using DiabetesApi.Models;

namespace DiabetesApi.Controllers;

/// <summary>Anomaly detection results and acknowledgement.</summary>
[ApiController]
[Route("api/anomalies")]
[Produces("application/json")]
public class AnomaliesController(AppDbContext db) : ControllerBase
{
    /// <summary>
    /// Get detected anomalies for a patient.
    /// </summary>
    /// <param name="patientId">Patient ID.</param>
    /// <param name="acknowledged">Filter by acknowledgement status (true/false, optional).</param>
    /// <param name="limit">Maximum number of results (default 50).</param>
    [HttpGet("{patientId:int}")]
    [ProducesResponseType(typeof(AnomaliesResponse), StatusCodes.Status200OK)]
    public async Task<IActionResult> GetAnomalies(
        int patientId,
        [FromQuery] bool? acknowledged = null,
        [FromQuery] int limit = 50)
    {
        var query = db.AnomalyDetections.Where(a => a.PatientId == patientId);

        if (acknowledged.HasValue)
            query = query.Where(a => a.IsAcknowledged == acknowledged.Value);

        var anomalies = await query
            .OrderByDescending(a => a.DetectedAt)
            .Take(limit)
            .ToListAsync();

        return Ok(new AnomaliesResponse(
            patientId,
            anomalies.Select(ToDto),
            anomalies.Count
        ));
    }

    /// <summary>Mark an anomaly as acknowledged by a clinician.</summary>
    [HttpPost("{anomalyId:int}/acknowledge")]
    [ProducesResponseType(typeof(AnomalyDetectionDto), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> AcknowledgeAnomaly(int anomalyId)
    {
        var anomaly = await db.AnomalyDetections.FindAsync(anomalyId);
        if (anomaly is null) return NotFound();

        anomaly.IsAcknowledged = true;
        await db.SaveChangesAsync();

        return Ok(ToDto(anomaly));
    }

    private static AnomalyDetectionDto ToDto(AnomalyDetection a) => new(
        a.Id,
        a.PatientId,
        a.GlucoseReadingId,
        a.AnomalyType,
        a.Confidence,
        a.Description,
        a.IsAcknowledged,
        a.DetectedAt.ToString("O")
    );
}
