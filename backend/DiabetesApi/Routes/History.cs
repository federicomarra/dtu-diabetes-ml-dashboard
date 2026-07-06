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
                getLatestTimestamp: () => db.Histories
                    .Where(h => h.PatientId == id)
                    .Select(h => (DateTime?)h.Timestamp)
                    .MaxAsync());

            if (range is null)
                return BadRequest(new { error = "Invalid last parameter format. Use e.g. 24h, 7d, 2w, 1m." });

            s = range.Value.start;
            e = range.Value.end;
        }

        query = query.Where(h => h.Timestamp >= s && h.Timestamp <= e);

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
