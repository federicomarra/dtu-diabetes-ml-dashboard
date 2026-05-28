using Microsoft.AspNetCore.Mvc;

namespace DiabetesApi.Routes;

/// <summary>API health check.</summary>
[ApiController]
[Route("api")]
public class Health : ControllerBase
{
    /// <summary>Returns the health status of the API.</summary>
    [HttpGet("health")]
    [ProducesResponseType(typeof(object), StatusCodes.Status200OK)]
    public IActionResult GetHealth() =>
        Ok(new { status = "healthy" });
}
