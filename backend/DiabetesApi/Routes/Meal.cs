using Microsoft.AspNetCore.Mvc;
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
    /// <param name="patientId">Patient ID</param>
    /// <param name="start">ISO datetime string (optional)</param>
    /// <param name="end">ISO datetime string (optional)</param>
    /// <param name="last">Last time period (e.g. "24h", "7d", "2w", "1m") (optional, default '2w' if no start/end specified)</param>
    [HttpGet("{patientId:int}")]
    [ProducesResponseType(typeof(MealsResponse), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> GetMeals(
        int patientId,
        [FromQuery] string? start = null,
        [FromQuery] string? end   = null,
        [FromQuery] string? last  = null)
    {
        var query = db.Meals.Where(m => m.PatientId == patientId);

        if (start is not null) {
            query = query.Where(m => m.Timestamp >= DateTime.Parse(start).ToUniversalTime());
        }
        if (end is not null) {
            query = query.Where(m => m.Timestamp <= DateTime.Parse(end).ToUniversalTime());
        }

        if (start is null && end is null && last is null) {
            last = "2w";
        }

        if (last is not null) {
            var latestTimestamp = await db.Meals
                .Where(m => m.PatientId == patientId)
                .Select(m => (DateTime?)m.Timestamp)
                .MaxAsync();

            var baseTime = latestTimestamp.HasValue
                ? DateTime.SpecifyKind(latestTimestamp.Value, DateTimeKind.Utc)
                : DateTime.UtcNow;

            if (last.EndsWith("h") && int.TryParse(last.Substring(0, last.Length - 1), out int hours))
            {
                query = query.Where(m => m.Timestamp >= baseTime.AddHours(-hours));
            }
            else if (last.EndsWith("d") && int.TryParse(last.Substring(0, last.Length - 1), out int days))
            {
                query = query.Where(m => m.Timestamp >= baseTime.AddDays(-days));
            }
            else if (last.EndsWith("w") && int.TryParse(last.Substring(0, last.Length - 1), out int weeks))
            {
                query = query.Where(m => m.Timestamp >= baseTime.AddDays(-weeks * 7));
            }
            else if (last.EndsWith("m") && int.TryParse(last.Substring(0, last.Length - 1), out int months))
            {
                query = query.Where(m => m.Timestamp >= baseTime.AddMonths(-months));
            }
            else
            {
                return BadRequest(new { error = "Invalid last parameter format. Use e.g. 24h, 7d, 2w, 1m." });
            }
        }

        var items = await query
            .OrderByDescending(m => m.Timestamp)
            .ToListAsync();

        return Ok(new MealsResponse(
            patientId,
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
