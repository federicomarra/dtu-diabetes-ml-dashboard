using Microsoft.AspNetCore.Mvc;
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
    /// <summary>Get history data for a patient.</summary>
    /// <param name="patientId">Patient ID.</param>
    /// <param name="limit">Maximum number of results (default 100).</param>
    [HttpGet("{patientId:int}")]
    [ProducesResponseType(typeof(HistoriesResponse), StatusCodes.Status200OK)]
    public async Task<IActionResult> GetHistory(int patientId, [FromQuery] int limit = 100)
    {
        var items = await db.Histories
            .Where(h => h.PatientId == patientId)
            .OrderByDescending(h => h.Timestamp)
            .Take(limit)
            .ToListAsync();

        return Ok(new HistoriesResponse(
            patientId,
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
