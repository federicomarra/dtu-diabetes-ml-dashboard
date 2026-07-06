using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.ModelBinding;
using Microsoft.EntityFrameworkCore;
using DiabetesApi.Data;
using DiabetesApi.Models;

namespace DiabetesApi.Routes;

/// <summary>Meal carbohydrate intake endpoints.</summary>
[ApiController]
[Route("api/meal")]
[Produces("application/json")]
public class Meal(AppDbContext db) : ControllerBase
{
    /// <summary>
    /// Get meal events for a patient within an optional time range or duration.
    /// </summary>
    /// <param name="id">Patient ID</param>
    /// <param name="start">ISO datetime string (optional)</param>
    /// <param name="end">ISO datetime string (optional)</param>
    /// <param name="last">Last time period (e.g. "24h", "7d", "2w", "1m") (optional, default '2w' if no start/end specified)</param>
    [HttpGet]
    [ProducesResponseType(typeof(MealsResponse), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> GetMeals(
        [FromQuery, BindRequired] int id,
        [FromQuery] string? start = null,
        [FromQuery] string? end   = null,
        [FromQuery] string? last  = null)
    {
        var query = db.Meals.Where(m => m.PatientId == id);

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
                getLatestTimestamp: () => db.Meals
                    .Where(m => m.PatientId == id)
                    .Select(m => (DateTime?)m.Timestamp)
                    .MaxAsync());

            if (range is null)
                return BadRequest(new { error = "Invalid last parameter format. Use e.g. 24h, 7d, 2w, 1m." });

            s = range.Value.start;
            e = range.Value.end;
        }

        query = query.Where(m => m.Timestamp >= s && m.Timestamp <= e);

        var items = await query
            .OrderByDescending(m => m.Timestamp)
            .ToListAsync();

        return Ok(new MealsResponse(
            id,
            items.Select(ToDto),
            items.Count
        ));
    }

    private static MealDto ToDto(Models.Meal m) => new(
        m.Id,
        m.PatientId,
        m.Timestamp.ToString("O"),
        (float)m.Carbs,
        m.MealType
    );
}
