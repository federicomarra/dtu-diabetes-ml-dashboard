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
    /// <summary>Get meal events for a patient.</summary>
    /// <param name="patientId">Patient ID.</param>
    /// <param name="limit">Maximum number of results (default 100).</param>
    [HttpGet("{patientId:int}")]
    [ProducesResponseType(typeof(MealsResponse), StatusCodes.Status200OK)]
    public async Task<IActionResult> GetMeals(int patientId, [FromQuery] int limit = 100)
    {
        var items = await db.Meals
            .Where(m => m.PatientId == patientId)
            .OrderByDescending(m => m.Timestamp)
            .Take(limit)
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
