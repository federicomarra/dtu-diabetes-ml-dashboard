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
                getLatestTimestamp: () => db.Insulins
                    .Where(i => i.PatientId == id)
                    .Select(i => (DateTime?)i.Timestamp)
                    .MaxAsync());

            if (range is null)
                return BadRequest(new { error = "Invalid last parameter format. Use e.g. 24h, 7d, 2w, 1m." });

            s = range.Value.start;
            e = range.Value.end;
        }

        query = query.Where(i => i.Timestamp >= s && i.Timestamp <= e);

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
