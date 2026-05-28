using Microsoft.AspNetCore.Mvc;
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
    /// <summary>Get insulin events for a patient.</summary>
    /// <param name="patientId">Patient ID.</param>
    /// <param name="limit">Maximum number of results (default 100).</param>
    [HttpGet("{patientId:int}")]
    [ProducesResponseType(typeof(InsulinsResponse), StatusCodes.Status200OK)]
    public async Task<IActionResult> GetInsulins(int patientId, [FromQuery] int limit = 100)
    {
        var items = await db.Insulins
            .Where(i => i.PatientId == patientId)
            .OrderByDescending(i => i.Timestamp)
            .Take(limit)
            .ToListAsync();

        return Ok(new InsulinsResponse(
            patientId,
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
