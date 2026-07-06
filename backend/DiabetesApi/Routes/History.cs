using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.ModelBinding;
using Microsoft.EntityFrameworkCore;
using DiabetesApi.Data;
using DiabetesApi.Models;

namespace DiabetesApi.Routes;

/// <summary>Historical data endpoints.</summary>
[ApiController]
[Route("api/history")]
[Produces("application/json")]
public class History(AppDbContext db) : ControllerBase
{
    /// <summary>
    /// Get history data for a patient within an optional time range or duration.
    /// </summary>
    /// <param name="id">Patient ID</param>
    /// <param name="start">ISO datetime string (optional)</param>
    /// <param name="end">ISO datetime string (optional)</param>
    /// <param name="last">Last time period (e.g. "24h", "7d", "2w", "1m") (optional, default '2w' if no start/end specified)</param>
    [HttpGet]
    [ProducesResponseType(typeof(HistoriesResponse), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> GetHistory(
        [FromQuery, BindRequired] int id,
        [FromQuery] string? start = null,
        [FromQuery] string? end   = null,
        [FromQuery] string? last  = null)
    {
        var query = db.Histories.Where(h => h.PatientId == id);

        if (start is not null) {
            query = query.Where(h => h.Timestamp >= DateTime.Parse(start).ToUniversalTime());
        }
        if (end is not null) {
            query = query.Where(h => h.Timestamp <= DateTime.Parse(end).ToUniversalTime());
        }

        if (start is null && end is null && last is null) {
            last = "2w";
        }

        if (last is not null) {
            var latestTimestamp = await db.Histories
                .Where(h => h.PatientId == id)
                .Select(h => (DateTime?)h.Timestamp)
                .MaxAsync();

            var baseTime = latestTimestamp.HasValue
                ? DateTime.SpecifyKind(latestTimestamp.Value, DateTimeKind.Utc)
                : DateTime.UtcNow;

            if (last.EndsWith("h") && int.TryParse(last.Substring(0, last.Length - 1), out int hours))
            {
                query = query.Where(h => h.Timestamp >= baseTime.AddHours(-hours));
            }
            else if (last.EndsWith("d") && int.TryParse(last.Substring(0, last.Length - 1), out int days))
            {
                query = query.Where(h => h.Timestamp >= baseTime.AddDays(-days));
            }
            else if (last.EndsWith("w") && int.TryParse(last.Substring(0, last.Length - 1), out int weeks))
            {
                query = query.Where(h => h.Timestamp >= baseTime.AddDays(-weeks * 7));
            }
            else if (last.EndsWith("m") && int.TryParse(last.Substring(0, last.Length - 1), out int months))
            {
                query = query.Where(h => h.Timestamp >= baseTime.AddMonths(-months));
            }
            else
            {
                return BadRequest(new { error = "Invalid last parameter format. Use e.g. 24h, 7d, 2w, 1m." });
            }
        }

        var items = await query
            .OrderByDescending(h => h.Timestamp)
            .ToListAsync();

        return Ok(new HistoriesResponse(
            id,
            items.Select(ToDto),
            items.Count
        ));
    }

    private static HistoryDto ToDto(Models.History h) => new(
        h.Id,
        h.PatientId,
        h.Timestamp.ToString("O"),
        h.Glucose,
        h.Insulin,
        h.Meal
    );
}
