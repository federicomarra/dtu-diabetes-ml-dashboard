using Microsoft.AspNetCore.Mvc;

namespace DiabetesApi.Controllers;

/// <summary>API health check.</summary>
[ApiController]
[Route("api")]
public class HealthController : ControllerBase
{
    /// <summary>Returns the health status of the API.</summary>
    [HttpGet("health")]
    [ProducesResponseType(typeof(object), StatusCodes.Status200OK)]
    public IActionResult GetHealth() =>
        Ok(new { status = "healthy" });
}
