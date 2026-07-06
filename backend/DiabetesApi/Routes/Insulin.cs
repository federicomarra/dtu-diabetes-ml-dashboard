using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.ModelBinding;
using Microsoft.EntityFrameworkCore;
using DiabetesApi.Data;
using DiabetesApi.Models;

namespace DiabetesApi.Routes;

/// <summary>Insulin delivery data endpoints.</summary>
[ApiController]
[Route("api/insulin")]
[Produces("application/json")]
public class Insulin(AppDbContext db) : ControllerBase
{
    /// <summary>
    /// Get insulin events for a patient within an optional time range or duration.
    /// </summary>
    /// <param name="id">Patient ID</param>
    /// <param name="start">ISO datetime string (optional)</param>
    /// <param name="end">ISO datetime string (optional)</param>
    /// <param name="last">Last time period (e.g. "24h", "7d", "2w", "1m") (optional, default '2w' if no start/end specified)</param>
    [HttpGet]
    [ProducesResponseType(typeof(InsulinsResponse), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> GetInsulins(
        [FromQuery, BindRequired] int id,
        [FromQuery] string? start = null,
        [FromQuery] string? end   = null,
        [FromQuery] string? last  = null)
    {
        var query = db.Insulins.Where(i => i.PatientId == id);

        if (start is not null) {
            query = query.Where(i => i.Timestamp >= DateTime.Parse(start).ToUniversalTime());
        }
        if (end is not null) {
            query = query.Where(i => i.Timestamp <= DateTime.Parse(end).ToUniversalTime());
        }

        if (start is null && end is null && last is null) {
            last = "2w";
        }

        if (last is not null) {
            var latestTimestamp = await db.Insulins
                .Where(i => i.PatientId == id)
                .Select(i => (DateTime?)i.Timestamp)
                .MaxAsync();

            var baseTime = latestTimestamp.HasValue
                ? DateTime.SpecifyKind(latestTimestamp.Value, DateTimeKind.Utc)
                : DateTime.UtcNow;

            if (last.EndsWith("h") && int.TryParse(last.Substring(0, last.Length - 1), out int hours))
            {
                query = query.Where(i => i.Timestamp >= baseTime.AddHours(-hours));
            }
            else if (last.EndsWith("d") && int.TryParse(last.Substring(0, last.Length - 1), out int days))
            {
                query = query.Where(i => i.Timestamp >= baseTime.AddDays(-days));
            }
            else if (last.EndsWith("w") && int.TryParse(last.Substring(0, last.Length - 1), out int weeks))
            {
                query = query.Where(i => i.Timestamp >= baseTime.AddDays(-weeks * 7));
            }
            else if (last.EndsWith("m") && int.TryParse(last.Substring(0, last.Length - 1), out int months))
            {
                query = query.Where(i => i.Timestamp >= baseTime.AddMonths(-months));
            }
            else
            {
                return BadRequest(new { error = "Invalid last parameter format. Use e.g. 24h, 7d, 2w, 1m." });
            }
        }

        var items = await query
            .OrderByDescending(i => i.Timestamp)
            .ToListAsync();

        return Ok(new InsulinsResponse(
            id,
            items.Select(ToDto),
            items.Count
        ));
    }

    private static InsulinDto ToDto(Models.Insulin i) => new(
        i.Id,
        i.PatientId,
        i.Timestamp.ToString("O"),
        (float)i.Units,
        i.EventType
    );
}
